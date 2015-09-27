import sys
import math
import random
import traceback
import maya.mel as mel
import pymel.core as pm
import maya.OpenMaya as OpenMaya
import maya.OpenMayaUI as OpenMayaUI
import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMayaRender as OpenMayaRender

kPluginCmdName = "instanceAlongCurve"
kPluginCtxCmdName = "instanceAlongCurveCtx"
kPluginNodeName = 'instanceAlongCurveLocator'
kPluginManipNodeName = 'instanceAlongCurveLocatorManip'
kPluginNodeClassify = 'utility/general'
kPluginNodeId = OpenMaya.MTypeId( 0x55555 ) 
kPluginNodeManipId = OpenMaya.MTypeId( 0x55556 ) 

# InstanceAlongCurve v1.0.4
class instanceAlongCurveLocator(OpenMayaMPx.MPxLocatorNode):

    # Simple container class for compound vector attributes
    class Vector3CompoundAttribute(object):

        def __init__(self):            
            self.compound = OpenMaya.MObject()
            self.x = OpenMaya.MObject()
            self.y = OpenMaya.MObject()
            self.z = OpenMaya.MObject()

    class CurveAxisHandleAttribute(object):

        def __init__(self):
            self.compound = OpenMaya.MObject()
            self.parameter = OpenMaya.MObject()
            self.axis = OpenMaya.MObject() # The curve axis in the specified parameter

    # Input attributes
    inputCurveAttr = OpenMaya.MObject()
    inputTransformAttr = OpenMaya.MObject()
    inputShadingGroupAttr = OpenMaya.MObject()

    # Instance count related attributes
    instanceCountAttr = OpenMaya.MObject()
    instancingModeAttr = OpenMaya.MObject()
    instanceLengthAttr = OpenMaya.MObject()
    maxInstancesByLengthAttr = OpenMaya.MObject()

    # Curve axis data, to be manipulated by user
    curveAxisHandleAttr = CurveAxisHandleAttribute()

    displayTypeAttr = OpenMaya.MObject()
    bboxAttr = OpenMaya.MObject()

    orientationModeAttr = OpenMaya.MObject()
    inputOrientationAxisAttr = Vector3CompoundAttribute()

    class RampAttributes(object):

        def __init__(self):
            self.ramp = OpenMaya.MObject() # normalized ramp
            self.rampOffset = OpenMaya.MObject() # evaluation offset for ramp
            self.rampAxis = OpenMaya.MObject() # ramp normalized axis
            self.rampAmplitude = OpenMaya.MObject() # ramp amplitude
            self.rampRandomAmplitude = OpenMaya.MObject() # ramp random amplitude

    # Simple container class for compound vector attributes
    class RampValueContainer(object):

        def __init__(self, mObject, dataBlock, rampAttr, normalize):            
            self.ramp = OpenMaya.MRampAttribute(OpenMaya.MPlug(mObject, rampAttr.ramp))
            self.rampOffset = dataBlock.inputValue(rampAttr.rampOffset).asFloat()
            self.rampRandomAmplitude = dataBlock.inputValue(rampAttr.rampRandomAmplitude).asFloat()
            self.rampAmplitude = dataBlock.inputValue(rampAttr.rampAmplitude).asFloat()

            if normalize:
                self.rampAxis = dataBlock.inputValue(rampAttr.rampAxis.compound).asVector().normal()
            else:
                self.rampAxis = dataBlock.inputValue(rampAttr.rampAxis.compound).asVector()              

    # Ramps base offset
    distOffsetAttr = OpenMaya.MObject()

    # Ramp attributes
    positionRampAttr = RampAttributes()
    rotationRampAttr = RampAttributes()
    scaleRampAttr = RampAttributes()

    # Output vectors
    outputTranslationAttr = Vector3CompoundAttribute()
    outputRotationAttr = Vector3CompoundAttribute()
    outputScaleAttr = Vector3CompoundAttribute()

    def __init__(self):
        OpenMayaMPx.MPxLocatorNode.__init__(self)

    def postConstructor(self):
        OpenMaya.MFnDependencyNode(self.thisMObject()).setName("instanceAlongCurveLocatorShape#")
        self.callbackId = OpenMaya.MNodeMessage.addAttributeChangedCallback(self.thisMObject(), self.attrChangeCallback)
        self.updateInstanceConnections()

    # Find original SG to reassign it to instance
    def getShadingGroup(self):
        inputSGPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputShadingGroupAttr)
        sgNode = self.getSingleSourceObjectFromPlug(inputSGPlug)

        if sgNode is not None and sgNode.hasFn(OpenMaya.MFn.kSet):
            return OpenMaya.MFnSet(sgNode)

        return None

    def assignShadingGroup(self, fnDagNode):

        fnSet = self.getShadingGroup()

        if fnSet is not None:
            # Easiest, cleanest way seems to be calling MEL.
            # sets command handles everything, even nested instanced dag paths
            mdgm = OpenMaya.MDGModifier()
            mdgm.commandToExecute("sets -e -nw -fe " + fnSet.name() + " " + fnDagNode.name())
            mdgm.doIt()

    # Helper function to get an array of available logical indices from the sparse array
    # TODO: maybe it can be precalculated?
    def getAvailableLogicalIndices(self, plug, numIndices):
        
        # Allocate and initialize
        outIndices = OpenMaya.MIntArray(numIndices)
        indices = OpenMaya.MIntArray(plug.numElements())
        plug.getExistingArrayAttributeIndices(indices)

        currentAvailableIndex = 0
        indicesFound = 0

        # Assuming indices are SORTED :)
        for i in indices:

            connectedPlug = plug.elementByLogicalIndex(i).isConnected()

            # Iteratively find available indices in the sparse array
            while i > currentAvailableIndex:
                outIndices[indicesFound] = currentAvailableIndex
                indicesFound += 1
                currentAvailableIndex += 1

            # Check against this index, add it if it is not connected
            if i == currentAvailableIndex and not connectedPlug:
                outIndices[indicesFound] = currentAvailableIndex
                indicesFound += 1

            currentAvailableIndex += 1

            if indicesFound == numIndices:
                return outIndices

        # Fill remaining expected indices
        for i in xrange(indicesFound, numIndices):
            outIndices[i] = currentAvailableIndex
            currentAvailableIndex += 1

        return outIndices

    def getNodeTransformFn(self):
        dagNode = OpenMaya.MFnDagNode(self.thisMObject())
        dagPath = OpenMaya.MDagPath()
        dagNode.getPath(dagPath)
        return OpenMaya.MFnDagNode(dagPath.transform())

    def updateInstanceConnections(self):

        # If the locator is being instanced, just stop updating its children.
        # This is to prevent losing references to the locator instances' children
        # If you want to change this locator, prepare the source before instantiating
        if OpenMaya.MFnDagNode(self.thisMObject()).isInstanced():
            return OpenMaya.kUnknownParameter

        # Plugs
        outputTranslationPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.outputTranslationAttr.compound)
        outputRotationPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.outputRotationAttr.compound)
        outputScalePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.outputScaleAttr.compound)

        expectedInstanceCount = self.getInstanceCountByMode()
        numConnectedElements = outputTranslationPlug.numConnectedElements()

        # Only instance if we are missing elements
        # TODO: handle mismatches in translation/rotation plug connected elements (user deleted a plug? use connectionBroken method?)
        if numConnectedElements < expectedInstanceCount:

            inputTransformFn = self.getInputTransformFn()

            if inputTransformFn is not None:

                transformFn = self.getNodeTransformFn()
                newInstancesCount = expectedInstanceCount - numConnectedElements
                availableIndices = self.getAvailableLogicalIndices(outputTranslationPlug, newInstancesCount)

                displayPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.displayTypeAttr)
                LODPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.bboxAttr)

                mdgModifier = OpenMaya.MDagModifier()

                for i in availableIndices:
                    
                    # Instance transform
                    # InstanceLeaf must be set to False to prevent crashes :)
                    trInstance = inputTransformFn.duplicate(True, False)
                    instanceFn = OpenMaya.MFnTransform(trInstance)

                    # Parent new instance
                    transformFn.addChild(trInstance)

                    instanceTranslatePlug = instanceFn.findPlug('translate', False)
                    outputTranslationPlugElement = outputTranslationPlug.elementByLogicalIndex(i)

                    instanceRotationPlug = instanceFn.findPlug('rotate', False)
                    outputRotationPlugElement = outputRotationPlug.elementByLogicalIndex(i)

                    instanceScalePlug = instanceFn.findPlug('scale', False)
                    outputScalePlugElement = outputScalePlug.elementByLogicalIndex(i)

                    # Enable drawing overrides
                    overrideEnabledPlug = instanceFn.findPlug("overrideEnabled", False)
                    overrideEnabledPlug.setBool(True)

                    instanceDisplayPlug = instanceFn.findPlug("overrideDisplayType", False)
                    instanceLODPlug = instanceFn.findPlug("overrideLevelOfDetail", False)

                    if not outputTranslationPlugElement.isConnected():
                        mdgModifier.connect(outputTranslationPlugElement, instanceTranslatePlug)

                    if not outputRotationPlugElement.isConnected():
                        mdgModifier.connect(outputRotationPlugElement, instanceRotationPlug)

                    if not outputScalePlugElement.isConnected():
                        mdgModifier.connect(outputScalePlugElement, instanceScalePlug)

                    if not instanceDisplayPlug.isConnected():
                        mdgModifier.connect(displayPlug, instanceDisplayPlug)

                    if not instanceLODPlug.isConnected():
                        mdgModifier.connect(LODPlug, instanceLODPlug)

                mdgModifier.doIt()

                # Finally, assign SG to all children
                self.assignShadingGroup(transformFn)

        # Remove instances if necessary
        elif numConnectedElements > expectedInstanceCount:

            connections = OpenMaya.MPlugArray()        
            toRemove = numConnectedElements - expectedInstanceCount
            mdgModifier = OpenMaya.MDGModifier()

            for i in xrange(toRemove):
                outputTranslationPlugElement = outputTranslationPlug.connectionByPhysicalIndex(numConnectedElements - 1 - i)
                outputTranslationPlugElement.connectedTo(connections, False, True)

                for c in xrange(connections.length()):
                    mdgModifier.deleteNode(connections[c].node())

            mdgModifier.doIt()

    def attrChangeCallback(self, msg, plug, otherPlug, clientData):

        incomingDirection = (OpenMaya.MNodeMessage.kIncomingDirection & msg) == OpenMaya.MNodeMessage.kIncomingDirection
        attributeSet = (OpenMaya.MNodeMessage.kAttributeSet & msg) == OpenMaya.MNodeMessage.kAttributeSet
        isCorrectAttribute = (plug.attribute() == instanceAlongCurveLocator.instanceCountAttr) 
        isCorrectAttribute = isCorrectAttribute or (plug.attribute() == instanceAlongCurveLocator.instancingModeAttr)
        isCorrectAttribute = isCorrectAttribute or (plug.attribute() == instanceAlongCurveLocator.instanceLengthAttr)
        isCorrectAttribute = isCorrectAttribute or (plug.attribute() == instanceAlongCurveLocator.maxInstancesByLengthAttr)
        isCorrectNode = OpenMaya.MFnDependencyNode(plug.node()).typeName() == kPluginNodeName

        try:
            if isCorrectNode and isCorrectAttribute and attributeSet and incomingDirection:
                self.updateInstanceConnections()
        except:    
            sys.stderr.write('Failed trying to update instances. stack trace: \n')
            sys.stderr.write(traceback.format_exc())

    def getSingleSourceObjectFromPlug(self, plug):

        if plug.isConnected():
            # Get connected input plugs
            connections = OpenMaya.MPlugArray()
            plug.connectedTo(connections, True, False)

            # Find input transform
            if connections.length() == 1:
                return connections[0].node()

        return None

    def getInputTransformFn(self):
        inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
        transform = self.getSingleSourceObjectFromPlug(inputTransformPlug)

        # Get Fn from a DAG path to get the world transformations correctly
        if transform is not None and transform.hasFn(OpenMaya.MFn.kTransform):
                path = OpenMaya.MDagPath()
                trFn = OpenMaya.MFnDagNode(transform)
                trFn.getPath(path)
                return OpenMaya.MFnTransform(path)

        return None

    def getCurveFn(self):
        inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)
        curve = self.getSingleSourceObjectFromPlug(inputCurvePlug)

        # Get Fn from a DAG path to get the world transformations correctly
        if curve is not None:
            path = OpenMaya.MDagPath()
            trFn = OpenMaya.MFnDagNode(curve)
            trFn.getPath(path)

            path.extendToShape()

            if path.node().hasFn(OpenMaya.MFn.kNurbsCurve):
                return OpenMaya.MFnNurbsCurve(path)

        return None

    # Calculate expected instances by the instancing mode
    def getInstanceCountByMode(self):
        instancingModePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instancingModeAttr)
        inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)

        if inputCurvePlug.isConnected() and instancingModePlug.asInt() == 1:
            instanceLengthPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instanceLengthAttr)
            maxInstancesByLengthPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.maxInstancesByLengthAttr)
            curveFn = self.getCurveFn()
            return min(maxInstancesByLengthPlug.asInt(), int(curveFn.length() / instanceLengthPlug.asFloat()))

        instanceCountPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instanceCountAttr)
        return instanceCountPlug.asInt()

    def getParamOffset(self):
        p = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.distOffsetAttr)
        return p.asFloat()

    def getRandomizedValue(self, random, randomAmplitude, value):
        return (random.random() * 2.0 - 1.0) * randomAmplitude + value

    def updateInstancePositions(self, curveFn, dataBlock, count, distOffset ):

            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            translateArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputTranslationAttr.compound)

            # Deterministic random
            random.seed(count)
            rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.positionRampAttr, False)

            # Make sure there are enough handles...
            for i in xrange(min(count, translateArrayHandle.elementCount())):

                rampValue = self.getRampValueAtPosition(rampValues, i, count)
                dist = math.fmod(curveLength * (i / float(count)) + distOffset, curveLength)

                # EP curves **really** dont like param at 0.0 
                param = max( min( curveFn.findParamFromLength( dist ), curveLength ), 0.001 )
                curveFn.getPointAtParam(param, point)

                try:
                    normal = curveFn.normal(param).normal()
                    tangent = curveFn.tangent(param).normal()
                    bitangent = (normal ^ tangent).normal()
                except:
                    print 'curveFn normal get error. param:%f/length:%f' % ( param, curveLength )

                twistNormal = normal * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.x
                twistBitangent = bitangent * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.y
                twistTangent = tangent * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.z

                point += twistNormal + twistTangent + twistBitangent

                translateArrayHandle.jumpToArrayElement(i)
                translateHandle = translateArrayHandle.outputValue()
                translateHandle.set3Double(point.x, point.y, point.z)

            translateArrayHandle.setAllClean()
            translateArrayHandle.setClean()

    def getRampValueAtPosition(self, rampValues, i, count):

        util = OpenMaya.MScriptUtil()
        util.createFromDouble(0.0)
        valuePtr = util.asFloatPtr()
        
        position = math.fmod((i / float(count)) + rampValues.rampOffset, 1.0)
        rampValues.ramp.getValueAtPosition(position, valuePtr)

        return util.getFloat(valuePtr)

    def updateInstanceScale(self, curveFn, dataBlock, count):

            point = OpenMaya.MPoint()
            scaleArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputScaleAttr.compound)

            # Deterministic random
            random.seed(count)
            rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.scaleRampAttr, False)

            # Make sure there are enough handles...
            for i in xrange(min(count, scaleArrayHandle.elementCount())):

                rampValue = self.getRampValueAtPosition(rampValues, i, count)

                point.x = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.x
                point.y = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.y
                point.z = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.z

                scaleArrayHandle.jumpToArrayElement(i)
                scaleHandle = scaleArrayHandle.outputValue()
                scaleHandle.set3Double(point.x, point.y, point.z)

            scaleArrayHandle.setAllClean()
            scaleArrayHandle.setClean()

    def updateInstanceRotations(self, curveFn, dataBlock, count, distOffset ):
            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            rotationArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputRotationAttr.compound)
            startOrientation = dataBlock.outputValue(instanceAlongCurveLocator.inputOrientationAxisAttr.compound).asVector().normal()

            # Deterministic random
            random.seed(count)
            rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.rotationRampAttr, True)

            rotMode = dataBlock.inputValue(instanceAlongCurveLocator.orientationModeAttr).asInt()

            inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
            inputTransformRotation = OpenMaya.MQuaternion()

            if inputTransformPlug.isConnected():
                self.getInputTransformFn().getRotation(inputTransformRotation, OpenMaya.MSpace.kWorld)

            for i in xrange(min(count, rotationArrayHandle.elementCount())):

                rampValue = self.getRampValueAtPosition(rampValues, i, count)
 
                dist = math.fmod(curveLength * (i / float(count)) + distOffset, curveLength)

                # EP curves **really** dont like param at 0.0
                param = max( min( curveFn.findParamFromLength( dist ), curveLength ), 0.002 )

                rot = OpenMaya.MQuaternion()
                try:
                    normal = curveFn.normal(param).normal()
                    tangent = curveFn.tangent(param).normal()
                    bitangent = (normal ^ tangent).normal()
                except:
                    print 'curveFn normal get error. param:%f/length:%f' % ( param, curveLength )
            
                if rotMode == 1:
                    rot = inputTransformRotation;
                elif rotMode == 2:
                    rot = startOrientation.rotateTo(normal)
                elif rotMode == 3:
                    rot = startOrientation.rotateTo(tangent)
                elif rotMode == 4:
                    rot = startOrientation.rotateTo(tangent)
                    
                    if i % 2 == 1:
                        rot *= OpenMaya.MQuaternion(3.141592 * .5, tangent)

                twistNormal = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.x                
                twistNormal = OpenMaya.MQuaternion(twistNormal * 0.0174532925, normal) # DegToRad

                twistTangent = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.y
                twistTangent = OpenMaya.MQuaternion(twistTangent * 0.0174532925, tangent) # DegToRad

                twistBitangent = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.z
                twistBitangent = OpenMaya.MQuaternion(twistBitangent * 0.0174532925, bitangent) # DegToRad

                rot = (rot * twistNormal * twistTangent * twistBitangent).asEulerRotation().asVector()

                rotationArrayHandle.jumpToArrayElement(i)
                rotationHandle = rotationArrayHandle.outputValue()
                rotationHandle.set3Double(rot.x, rot.y, rot.z)

            rotationArrayHandle.setAllClean()
            rotationArrayHandle.setClean()

    def isBounded(self):
        return True

    def boundingBox(self):
        return OpenMaya.MBoundingBox(OpenMaya.MPoint(-1,-1,-1), OpenMaya.MPoint(1,1,1))

    def compute(self, plug, dataBlock):
        try:
            curveDataHandle = dataBlock.inputValue(instanceAlongCurveLocator.inputCurveAttr)
            curve = curveDataHandle.asNurbsCurveTransformed()

            if not curve.isNull():
                curveFn = OpenMaya.MFnNurbsCurve(curve)

                instanceCount = self.getInstanceCountByMode()
                distOffset = self.getParamOffset()

                if plug == instanceAlongCurveLocator.outputTranslationAttr.compound:
                    self.updateInstancePositions(curveFn, dataBlock, instanceCount, distOffset)

                if plug == instanceAlongCurveLocator.outputRotationAttr.compound:
                    self.updateInstanceRotations(curveFn, dataBlock, instanceCount, distOffset)

                if plug == instanceAlongCurveLocator.outputScaleAttr.compound:
                    self.updateInstanceScale(curveFn, dataBlock, instanceCount)

        except:
            sys.stderr.write('Failed trying to compute locator. stack trace: \n')
            sys.stderr.write(traceback.format_exc())
            return OpenMaya.kUnknownParameter

    @staticmethod
    def nodeCreator():
        return OpenMayaMPx.asMPxPtr( instanceAlongCurveLocator() )

    @classmethod
    def addCompoundVector3Attribute(cls, compoundAttribute, attributeName, unitType, arrayAttr, inputAttr, defaultValue):

        # Schematic view of compound attribute:
        # compoundAttribute[?]
        #   compoundAttributeX
        #   compoundAttributeY
        #   compoundAttributeZ

        unitAttr = OpenMaya.MFnUnitAttribute()
        nAttr = OpenMaya.MFnNumericAttribute()

        compoundAttribute.x = unitAttr.create(attributeName + "X", attributeName + "X", unitType, defaultValue.x)
        unitAttr.setWritable( inputAttr )
        cls.addAttribute(compoundAttribute.x)

        compoundAttribute.y = unitAttr.create(attributeName + "Y", attributeName + "Y", unitType, defaultValue.y)
        unitAttr.setWritable( inputAttr )
        cls.addAttribute(compoundAttribute.y)

        compoundAttribute.z = unitAttr.create(attributeName + "Z", attributeName + "Z", unitType, defaultValue.z)
        unitAttr.setWritable( inputAttr )
        cls.addAttribute(compoundAttribute.z)

        # Output compound
        compoundAttribute.compound = nAttr.create(attributeName, attributeName,
                                     compoundAttribute.x, compoundAttribute.y, compoundAttribute.z)
        nAttr.setWritable( inputAttr )
        nAttr.setArray( arrayAttr )
        nAttr.setUsesArrayDataBuilder( arrayAttr )
        nAttr.setDisconnectBehavior(OpenMaya.MFnAttribute.kDelete)
        cls.addAttribute(compoundAttribute.compound)

    @classmethod
    def addRampAttributes(cls, rampAttributes, attributeName, unitType, defaultAxisValue):

        # Not a compound attribute, just adds them all to the node
        
        nAttr = OpenMaya.MFnNumericAttribute()

        rampAttributes.ramp = OpenMaya.MRampAttribute.createCurveRamp(attributeName + "Ramp", attributeName + "Ramp")
        cls.addAttribute(rampAttributes.ramp)

        rampAttributes.rampOffset = nAttr.create(attributeName + "RampOffset", attributeName + "RampOffset", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setKeyable( True )
        cls.addAttribute( rampAttributes.rampOffset )

        rampAttributes.rampAmplitude = nAttr.create(attributeName + "RampAmplitude", attributeName + "RampAmplitude", OpenMaya.MFnNumericData.kFloat, 1.0)
        nAttr.setKeyable( True )
        cls.addAttribute( rampAttributes.rampAmplitude )

        rampAttributes.rampRandomAmplitude = nAttr.create(attributeName + "RampRandomAmplitude", attributeName + "RampRandomAmplitude", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setMin(0.0)
        nAttr.setSoftMax(1.0)
        nAttr.setKeyable( True )
        cls.addAttribute( rampAttributes.rampRandomAmplitude )

        cls.addCompoundVector3Attribute(rampAttributes.rampAxis, attributeName + "RampAxis", unitType, False, True, defaultAxisValue)

    @classmethod
    def addCurveAxisHandleAttribute(cls, curveAxisHandleAttr, attributeName, defaultAxisValue):

        # Schematic view of compound attribute:
        # curveAxisHandle[]
        #   curveAxisHandleParameter
        #   curveAxisHandleAxis
        #       curveAxisHandleAxisX
        #       curveAxisHandleAxisY
        #       curveAxisHandleAxisZ

        nAttr = OpenMaya.MFnNumericAttribute()
        cmpAttr = OpenMaya.MFnCompoundAttribute()

        curveAxisHandleAttr.parameter = nAttr.create(attributeName + "Parameter", attributeName + "Parameter", OpenMaya.MFnNumericData.kDouble, 0.0)
        nAttr.setWritable( True )
        cls.addAttribute(curveAxisHandleAttr.parameter)

        cls.addCompoundVector3Attribute(curveAxisHandleAttr.axis, attributeName + "Axis", OpenMaya.MFnUnitAttribute.kAngle, False, True, defaultAxisValue)

        # Build compound array attribute
        curveAxisHandleAttr.compound = cmpAttr.create(attributeName, attributeName)
        cmpAttr.addChild(curveAxisHandleAttr.parameter)
        cmpAttr.addChild(curveAxisHandleAttr.axis.compound)
        cmpAttr.setWritable( True )
        cmpAttr.setArray( True )
        cmpAttr.setUsesArrayDataBuilder( True )

        cls.addAttribute(curveAxisHandleAttr.compound)

    @staticmethod
    def nodeInitializer():

        # Associate the node with its aim manipulator
        OpenMayaMPx.MPxManipContainer.addToManipConnectTable(kPluginNodeId)

        # To make things more readable
        node = instanceAlongCurveLocator

        nAttr = OpenMaya.MFnNumericAttribute()
        msgAttributeFn = OpenMaya.MFnMessageAttribute()
        curveAttributeFn = OpenMaya.MFnTypedAttribute()
        enumFn = OpenMaya.MFnEnumAttribute()

        node.inputTransformAttr = msgAttributeFn.create("inputTransform", "it")
        node.addAttribute( node.inputTransformAttr )

        node.inputShadingGroupAttr = msgAttributeFn.create("inputShadingGroup", "iSG")    
        node.addAttribute( node.inputShadingGroupAttr )

        # Input curve transform
        node.inputCurveAttr = curveAttributeFn.create( 'inputCurve', 'curve', OpenMaya.MFnData.kNurbsCurve)
        node.addAttribute( node.inputCurveAttr )
        
        ## Input instance count    
        node.instanceCountAttr = nAttr.create("instanceCount", "iic", OpenMaya.MFnNumericData.kInt, 5)
        nAttr.setMin(1)
        nAttr.setSoftMax(100)
        nAttr.setChannelBox( False )
        nAttr.setConnectable( False )
        node.addAttribute( node.instanceCountAttr)

        ## curve parameter start offset
        node.distOffsetAttr = nAttr.create("distOffset", "pOffset", OpenMaya.MFnNumericData.kFloat, 0.0)
        node.addAttribute( node.distOffsetAttr )

        ## Max instances when defined by instance length
        node.maxInstancesByLengthAttr = nAttr.create("maxInstancesByLength", "mibl", OpenMaya.MFnNumericData.kInt, 50)
        nAttr.setMin(0)
        nAttr.setSoftMax(200)
        nAttr.setChannelBox( False )
        nAttr.setConnectable( False )
        node.addAttribute( node.maxInstancesByLengthAttr)

        # Length between instances
        node.instanceLengthAttr = nAttr.create("instanceLength", "ilength", OpenMaya.MFnNumericData.kFloat, 1.0)
        nAttr.setMin(0.01)
        nAttr.setSoftMax(1.0)
        nAttr.setChannelBox( False )
        nAttr.setConnectable( False )
        node.addAttribute( node.instanceLengthAttr)

        # Display override options
        node.displayTypeAttr = enumFn.create('instanceDisplayType', 'idt')
        enumFn.addField( "Normal", 0 );
        enumFn.addField( "Template", 1 );
        enumFn.addField( "Reference", 2 );
        enumFn.setDefault("Reference")
        node.addAttribute( node.displayTypeAttr )

        # Enum for selection of instancing mode
        node.instancingModeAttr = enumFn.create('instancingMode', 'instancingMode')
        enumFn.addField( "Count", 0 );
        enumFn.addField( "Distance", 1 );
        node.addAttribute( node.instancingModeAttr )

         # Enum for selection of orientation mode
        node.orientationModeAttr = enumFn.create('orientationMode', 'rotMode')
        enumFn.addField( "Identity", 0 );
        enumFn.addField( "Copy from Source", 1 );
        enumFn.addField( "Normal", 2 );
        enumFn.addField( "Tangent", 3 );
        enumFn.addField( "Chain", 4 );
        enumFn.setDefault("Tangent")
        node.addAttribute( node.orientationModeAttr )

        node.addCompoundVector3Attribute(node.inputOrientationAxisAttr, "inputOrientationAxis", OpenMaya.MFnUnitAttribute.kDistance, False, True, OpenMaya.MVector(0.0, 0.0, 1.0))

        node.bboxAttr = nAttr.create('instanceBoundingBox', 'ibb', OpenMaya.MFnNumericData.kBoolean)
        node.addAttribute( node.bboxAttr )

        node.addRampAttributes(node.positionRampAttr, "position", OpenMaya.MFnUnitAttribute.kDistance, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addRampAttributes(node.rotationRampAttr, "rotation", OpenMaya.MFnUnitAttribute.kAngle, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addRampAttributes(node.scaleRampAttr, "scale", OpenMaya.MFnUnitAttribute.kDistance, OpenMaya.MVector(1.0, 1.0, 1.0))

        # Output attributes
        node.addCompoundVector3Attribute(node.outputTranslationAttr, "outputTranslation", OpenMaya.MFnUnitAttribute.kDistance, True, False, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.outputRotationAttr, "outputRotation", OpenMaya.MFnUnitAttribute.kAngle, True, False, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.outputScaleAttr, "outputScale", OpenMaya.MFnUnitAttribute.kDistance, True, False, OpenMaya.MVector(1.0, 1.0, 1.0))

        node.addCurveAxisHandleAttribute(node.curveAxisHandleAttr, "curveAxisHandle", OpenMaya.MVector(0.0,0.0,0.0))

        def rampAttributeAffects(rampAttributes, affectedAttr):
            node.attributeAffects( rampAttributes.ramp, affectedAttr)
            node.attributeAffects( rampAttributes.rampOffset, affectedAttr)
            node.attributeAffects( rampAttributes.rampAmplitude, affectedAttr)
            node.attributeAffects( rampAttributes.rampAxis.compound, affectedAttr)
            node.attributeAffects( rampAttributes.rampRandomAmplitude, affectedAttr)

        # Curve Axis affects, for manipulator
        node.attributeAffects( node.inputCurveAttr, node.curveAxisHandleAttr.compound )

        # Translation affects
        node.attributeAffects( node.inputCurveAttr, node.outputTranslationAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.distOffsetAttr, node.outputTranslationAttr.compound )

        rampAttributeAffects(node.positionRampAttr, node.outputTranslationAttr.compound)

        # Rotation affects
        node.attributeAffects( node.inputCurveAttr, node.outputRotationAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.orientationModeAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.distOffsetAttr, node.outputRotationAttr.compound )

        node.attributeAffects( node.inputOrientationAxisAttr.compound, node.outputRotationAttr.compound)

        rampAttributeAffects(node.rotationRampAttr, node.outputRotationAttr.compound)

        # Scale affects
        node.attributeAffects( node.inputCurveAttr, node.outputScaleAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.distOffsetAttr, node.outputScaleAttr.compound )

        rampAttributeAffects(node.scaleRampAttr, node.outputScaleAttr.compound)

###############
# AE TEMPLATE #
###############
def loadAETemplateCallback(nodeName):
    AEinstanceAlongCurveLocatorTemplate(nodeName)

class AEinstanceAlongCurveLocatorTemplate(pm.ui.AETemplate):

    def addControl(self, control, label=None, **kwargs):
        pm.ui.AETemplate.addControl(self, control, label=label, **kwargs)

    def beginLayout(self, name, collapse=True):
        pm.ui.AETemplate.beginLayout(self, name, collapse=collapse)

    def __init__(self, nodeName):
        pm.ui.AETemplate.__init__(self,nodeName)
        self.thisNode = None
        self.node = pm.PyNode(self.nodeName)

        if self.node.type() == kPluginNodeName:

            self.beginScrollLayout()
            self.beginLayout("Instance Along Curve Settings", collapse=0)

            self.addControl("instancingMode", label="Instancing Mode", changeCommand=self.onInstanceModeChanged)
            self.addControl("instanceCount", label="Count", changeCommand=self.onInstanceModeChanged)
            self.addControl("instanceLength", label="Distance", changeCommand=self.onInstanceModeChanged)
            self.addControl("maxInstancesByLength", label="Max Instances", changeCommand=self.onInstanceModeChanged)
            self.addControl("distOffset", label="Initial Position Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "distOffset"))
            
            self.addSeparator()

            self.addControl("orientationMode", label="Orientation Mode", changeCommand=lambda nodeName: self.updateDimming(nodeName, "orientationMode"))
            self.addControl("inputOrientationAxis", label="Orientation Axis", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputOrientationAxis"))

            self.addSeparator()

            self.addControl("instanceDisplayType", label="Instance Display Type", changeCommand=lambda nodeName: self.updateDimming(nodeName, "instanceDisplayType"))
            self.addControl("instanceBoundingBox", label="Use bounding box", changeCommand=lambda nodeName: self.updateDimming(nodeName, "instanceBoundingBox"))
            
            self.addSeparator()
            
            self.addControl("inputTransform", label="Input object", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputTransform"))
            self.addControl("inputShadingGroup", label="Shading Group", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputShadingGroup"))

            def showRampControls(rampName):

                self.beginLayout(rampName.capitalize() + " Control", collapse=True)
                mel.eval('AEaddRampControl("' + nodeName + "." + rampName + 'Ramp"); ')

                self.addControl(rampName + "RampOffset", label= rampName.capitalize() + " Ramp Offset")
                self.addControl(rampName + "RampAmplitude", label= rampName.capitalize() + " Ramp Amplitude")
                self.addControl(rampName + "RampRandomAmplitude", label= rampName.capitalize() + " Ramp Random")
                self.addControl(rampName + "RampAxis", label= rampName.capitalize() + " Ramp Axis")

                self.endLayout()

            showRampControls("position")
            showRampControls("rotation")
            showRampControls("scale")
            
            self.addExtraControls()

            self.endLayout()
            self.endScrollLayout()

    def onRampUpdate(self, attr):
        pm.gradientControl(attr)

    def updateDimming(self, nodeName, attr):

        if pm.PyNode(nodeName).type() == kPluginNodeName:

            node = pm.PyNode(nodeName)
            instanced = node.isInstanced()
            hasInputTransform = node.inputTransform.isConnected()
            hasInputCurve = node.inputCurve.isConnected()

            self.dimControl(nodeName, attr, instanced or (not hasInputCurve) or (not hasInputTransform))

    def onInstanceModeChanged(self, nodeName):
        self.updateDimming(nodeName, "instancingMode")

        if pm.PyNode(nodeName).type() == kPluginNodeName:

            nodeAttr = pm.PyNode(nodeName + ".instancingMode")
            mode = nodeAttr.get("instancingMode")

            # If dimmed, do not update dimming
            if mode == 0:
                self.dimControl(nodeName, "instanceLength", True)
                self.dimControl(nodeName, "maxInstancesByLength", True)

                self.updateDimming(nodeName, "instanceCount")
            else:
                self.updateDimming(nodeName, "instanceLength")
                self.updateDimming(nodeName, "maxInstancesByLength")
                
                self.dimControl(nodeName, "instanceCount", True)

# Command
class instanceAlongCurveCommand(OpenMayaMPx.MPxCommand):

    def __init__(self):
        OpenMayaMPx.MPxCommand.__init__(self)
        self.mUndo = []

    def isUndoable(self):
        return True

    def undoIt(self): 
        OpenMaya.MGlobal.displayInfo( "Undo: instanceAlongCurveCommand\n" )

        # Reversed for undo :)
        for m in reversed(self.mUndo):
            m.undoIt()

    def redoIt(self): 
        OpenMaya.MGlobal.displayInfo( "Redo: instanceAlongCurveCommand\n" )
        
        for m in self.mUndo:
            m.doIt()

    def hasShapeBelow(self, dagPath):

        sutil = OpenMaya.MScriptUtil()
        uintptr = sutil.asUintPtr()
        sutil.setUint(uintptr , 0)

        dagPath.numberOfShapesDirectlyBelow(uintptr)

        return sutil.getUint(uintptr) > 0

    def findShadingGroup(self, dagPath):

        # Search in children first before extending to shape
        for child in xrange(dagPath.childCount()):
            childDagPath = OpenMaya.MDagPath()
            fnDagNode = OpenMaya.MFnDagNode(dagPath.child(child))
            fnDagNode.getPath(childDagPath)

            fnSet = self.findShadingGroup(childDagPath)

            if fnSet is not None:
                return fnSet

        if self.hasShapeBelow(dagPath):
            dagPath.extendToShape()
            fnDepNode = OpenMaya.MFnDependencyNode(dagPath.node())

            instPlugArray = fnDepNode.findPlug("instObjGroups")
            instPlugArrayElem = instPlugArray.elementByLogicalIndex(dagPath.instanceNumber())

            if instPlugArrayElem.isConnected():
                connectedPlugs = OpenMaya.MPlugArray()      
                instPlugArrayElem.connectedTo(connectedPlugs, False, True)

                if connectedPlugs.length() == 1:
                    sgNode = connectedPlugs[0].node()

                    if sgNode.hasFn(OpenMaya.MFn.kSet):
                        return OpenMaya.MFnSet(sgNode)

        return None
        
    def doIt(self,argList):
        
        try:
            list = OpenMaya.MSelectionList()
            OpenMaya.MGlobal.getActiveSelectionList(list)

            if list.length() == 2:
                curveDagPath = OpenMaya.MDagPath()
                list.getDagPath(0, curveDagPath)
                curveDagPath.extendToShape()

                shapeDagPath = OpenMaya.MDagPath()
                list.getDagPath(1, shapeDagPath)           

                if(curveDagPath.node().hasFn(OpenMaya.MFn.kNurbsCurve)):

                    # We need the curve transform
                    curvePlug = OpenMaya.MFnDagNode(curveDagPath).findPlug("worldSpace", False).elementByLogicalIndex(0)

                    # We need the shape's transform too
                    transformFn = OpenMaya.MFnDagNode(shapeDagPath.transform())
                    transformMessagePlug = transformFn.findPlug("message", True)

                    shadingGroupFn = self.findShadingGroup(shapeDagPath)

                    # Create node first
                    mdagModifier = OpenMaya.MDagModifier()
                    self.mUndo.append(mdagModifier)
                    newNode = mdagModifier.createNode(kPluginNodeId)
                    mdagModifier.doIt()

                    # Assign new correct name and select new locator
                    newNodeFn = OpenMaya.MFnDagNode(newNode)
                    newNodeFn.setName("instanceAlongCurveLocator#")
                    newNodeTransformName = newNodeFn.name()

                    # Get the node shape
                    nodeShapeDagPath = OpenMaya.MDagPath()
                    newNodeFn.getPath(nodeShapeDagPath)
                    nodeShapeDagPath.extendToShape()
                    newNodeFn = OpenMaya.MFnDagNode(nodeShapeDagPath)

                    def setupRamp(rampAttr):

                        # Set default ramp values
                        defaultPositions = OpenMaya.MFloatArray(1, 0.0)
                        defaultValues = OpenMaya.MFloatArray(1, 1.0)
                        defaultInterpolations = OpenMaya.MIntArray(1, 3)

                        plug = newNodeFn.findPlug(rampAttr.ramp)
                        ramp = OpenMaya.MRampAttribute(plug)
                        ramp.addEntries(defaultPositions, defaultValues, defaultInterpolations)

                    setupRamp(instanceAlongCurveLocator.positionRampAttr)
                    setupRamp(instanceAlongCurveLocator.rotationRampAttr)
                    setupRamp(instanceAlongCurveLocator.scaleRampAttr)

                    # Select new node shape
                    OpenMaya.MGlobal.clearSelectionList()
                    msel = OpenMaya.MSelectionList()
                    msel.add(nodeShapeDagPath)
                    OpenMaya.MGlobal.setActiveSelectionList(msel)

                    # Connect :D
                    mdgModifier = OpenMaya.MDGModifier()
                    self.mUndo.append(mdgModifier)               
                    mdgModifier.connect(curvePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputCurveAttr))
                    mdgModifier.connect(transformMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputTransformAttr))

                    if shadingGroupFn is not None:
                        shadingGroupMessagePlug = shadingGroupFn.findPlug("message", True)
                        mdgModifier.connect(shadingGroupMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputShadingGroupAttr))

                    mdgModifier.doIt()

                    # (pymel) create a locator and make it the parent
                    locator = pm.createNode('locator', ss=True, p=newNodeTransformName)

                    # Show AE
                    mel.eval("openAEWindow")

                    instanceCountPlug = newNodeFn.findPlug("instanceCount", False)
                    instanceCountPlug.setInt(10)
                    
                else:
                    sys.stderr.write("Please select a curve first")
            else:
                sys.stderr.write("Please select a curve and a shape")
        except:
            sys.stderr.write('Failed trying to create locator. stack trace: \n')
            sys.stderr.write(traceback.format_exc())

    @staticmethod
    def cmdCreator():
        return OpenMayaMPx.asMPxPtr( instanceAlongCurveCommand() )

class instanceAlongCurveLocatorManip(OpenMayaMPx.MPxManipContainer):

    def __init__(self):
        OpenMayaMPx.MPxManipContainer.__init__(self)

        self.nodeFn = OpenMaya.MFnDependencyNode()

    @staticmethod
    def nodeCreator():
        return OpenMayaMPx.asMPxPtr( instanceAlongCurveLocatorManip() )

    @staticmethod
    def nodeInitializer():
        OpenMayaMPx.MPxManipContainer.initialize()

    def createChildren(self):
        self.manipCount = 5

        # TODO: here, precalculate curve data, because array plug size can change later
        # read current curveAxisHandle data
        # cache it in a temporary array
        # interpolate data for new plug size
        # [...]

        # List of tuples
        self.manipHandleList = []
        self.manipIndexCallbacks = {}

        for i in xrange(self.manipCount):
            pointOnCurveManip = self.addPointOnCurveManip("pointCurveManip" + str(i), "pointCurve" + str(i))
            rotateManip = self.addRotateManip("rotateManip" + str(i), "rotate" + str(i))
            freePointTriadManip = self.addFreePointTriadManip("freePointTriadManip" + str(i), "freePointTriad" + str(i))
            self.manipHandleList.append((pointOnCurveManip, rotateManip, freePointTriadManip))

    def connectToDependNode(self, node):

        self.nodeFn = OpenMaya.MFnDependencyNode(node)
        curvePlug = self.nodeFn.findPlug(instanceAlongCurveLocator.inputCurveAttr)        
        curveAxisHandleArrayPlug = self.nodeFn.findPlug(instanceAlongCurveLocator.curveAxisHandleAttr.compound)

        # Build and connect all plugs
        for i in xrange(self.manipCount):

            # Handle data
            curveAxisHandlePlug = curveAxisHandleArrayPlug.elementByLogicalIndex(i)
            curveParameterPlug = curveAxisHandlePlug.child(instanceAlongCurveLocator.curveAxisHandleAttr.parameter)
            curveAxisPlug = curveAxisHandlePlug.child(instanceAlongCurveLocator.curveAxisHandleAttr.axis.compound)

            fnCurvePoint = OpenMayaUI.MFnPointOnCurveManip(self.manipHandleList[i][0])
            fnCurvePoint.connectToCurvePlug(curvePlug)
            fnCurvePoint.connectToParamPlug(curveParameterPlug)
            fnCurvePoint.setParameter(float(i) / float(self.manipCount))

            fnRotate = OpenMayaUI.MFnRotateManip(self.manipHandleList[i][1])
            fnRotate.connectToRotationPlug(curveAxisPlug)
            fnRotate.setRotateMode(OpenMayaUI.MFnRotateManip.kObjectSpace) # Visualize better the rotations
            rotateManipIndex = fnRotate.rotationCenterIndex()
            self.addPlugToManipConversion(rotateManipIndex)
            self.manipIndexCallbacks[rotateManipIndex] = (self.rotationConversion, i) # Store index value 

            fnfreePointTriad = OpenMayaUI.MFnFreePointTriadManip(self.manipHandleList[i][2])
            fnfreePointTriad.setDrawArrowHead(False)
            pointIndex = fnfreePointTriad.pointIndex()
            self.addPlugToManipConversion(pointIndex)
            self.manipIndexCallbacks[pointIndex] = (self.freePointTriadConversion, i) # Store index value 

        self.finishAddingManips()        
        OpenMayaMPx.MPxManipContainer.connectToDependNode(self, node)

    def rotationConversion(self, manipTuple):

        fnCurvePoint = OpenMayaUI.MFnPointOnCurveManip(manipTuple[0])
        fnRotate = OpenMayaUI.MFnRotateManip(manipTuple[1])
        fnfreePointTriad = OpenMayaUI.MFnFreePointTriadManip(manipTuple[2])

        rotationCenter = fnCurvePoint.curvePoint()

        numData = OpenMaya.MFnNumericData()
        numDataObj = numData.create(OpenMaya.MFnNumericData.k3Double)
        numData.setData3Double(rotationCenter.x, rotationCenter.y, rotationCenter.z)
        manipData = OpenMayaUI.MManipData(numDataObj)
        return manipData

    def freePointTriadConversion(self, manipTuple):

        fnCurvePoint = OpenMayaUI.MFnPointOnCurveManip(manipTuple[0])
        fnRotate = OpenMayaUI.MFnRotateManip(manipTuple[1])
        fnfreePointTriad = OpenMayaUI.MFnFreePointTriadManip(manipTuple[2])

        # Update triad manip, dirty hack
        rotation = fnRotate.rotateXYZValue(fnRotate.rotationIndex())

        fnfreePointTriad.setTranslation(OpenMaya.MVector(fnCurvePoint.curvePoint()), OpenMaya.MSpace.kWorld)
        fnfreePointTriad.setRotation(rotation)

        numData = OpenMaya.MFnNumericData()
        numDataObj = numData.create(OpenMaya.MFnNumericData.k3Double)

        # Because the manipulator is being translated, the center has to be its origin
        numData.setData3Double(0.0, 0.0, 0.0)
        manipData = OpenMayaUI.MManipData(numDataObj)
        return manipData

    def plugToManipConversion(self, manipIndex):

        rotationCenter = OpenMaya.MPoint(0.0, 0.0, 0.0)

        if manipIndex in self.manipIndexCallbacks:
            curveHandleIndex = self.manipIndexCallbacks[manipIndex][1]
            return self.manipIndexCallbacks[manipIndex][0](self.manipHandleList[curveHandleIndex])

        print "Manip callback not set; returning invalid data!"

        numData = OpenMaya.MFnNumericData()
        numDataObj = numData.create(OpenMaya.MFnNumericData.k3Double)
        numData.setData3Double(0.0, 0.0, 0.0)
        manipData = OpenMayaUI.MManipData(numDataObj)
        return manipData

def initializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject, "mmerchante", "1.0.4" )
    try:
        # Register command
        mplugin.registerCommand( kPluginCmdName, instanceAlongCurveCommand.cmdCreator )

        if OpenMaya.MGlobal.mayaState() != OpenMaya.MGlobal.kBatch:
            mplugin.addMenuItem("Instance Along Curve", "MayaWindow|mainEditMenu", kPluginCmdName, "")

            # Register AE template
            pm.callbacks(addCallback=loadAETemplateCallback, hook='AETemplateCustomContent', owner=kPluginNodeName)

        # Register IAC node
        mplugin.registerNode( kPluginNodeName, kPluginNodeId, instanceAlongCurveLocator.nodeCreator,
                              instanceAlongCurveLocator.nodeInitializer, OpenMayaMPx.MPxNode.kLocatorNode, kPluginNodeClassify )

        # Register IAC manip node
        mplugin.registerNode( kPluginManipNodeName, kPluginNodeManipId, instanceAlongCurveLocatorManip.nodeCreator, instanceAlongCurveLocatorManip.nodeInitializer, OpenMayaMPx.MPxNode.kManipContainer )

    except:
        sys.stderr.write('Failed to register plugin instanceAlongCurve. stack trace: \n')
        sys.stderr.write(traceback.format_exc())
        raise
    
def uninitializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        mplugin.deregisterCommand( kPluginCmdName )
        mplugin.deregisterNode( kPluginNodeId )
        mplugin.deregisterNode( kPluginNodeManipId )
    except:
        sys.stderr.write( 'Failed to deregister plugin instanceAlongCurve')
        raise