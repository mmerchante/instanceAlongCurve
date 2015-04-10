import sys
import pdb
import math
import random
import traceback
import maya.mel as mel
import pymel.core as pm
import maya.OpenMaya as OpenMaya
import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMayaRender as OpenMayaRender

kPluginCmdName = "instanceAlongCurve"
kPluginNodeName = 'instanceAlongCurveLocator'
kPluginNodeClassify = 'utility/general'
kPluginNodeId = OpenMaya.MTypeId( 0x55555 ) 

glRenderer = OpenMayaRender.MHardwareRenderer.theRenderer()
glFT = glRenderer.glFunctionTable()

# Ideas:
#   - New orientation mode: follow last position. This is cool for random position or position ramp cases
#   - Random meshes
#   - New orientation mode: time warping on input transform. A nice domino effect can be done this way
#   - Modulate attributes (pos, rot, scale) along curve's parameter space through user defined curves
class instanceAlongCurveLocator(OpenMayaMPx.MPxLocatorNode):

    # Simple container class for compound vector attributes
    class Vector3CompoundAttribute(object):

        def __init__(self):            
            self.compound = OpenMaya.MObject()
            self.x = OpenMaya.MObject()
            self.y = OpenMaya.MObject()
            self.z = OpenMaya.MObject()

    # Input attributes
    inputCurveAttr = OpenMaya.MObject()
    inputTransformAttr = OpenMaya.MObject()
    inputShadingGroupAttr = OpenMaya.MObject()
    inputTimeAttr = OpenMaya.MObject()

    # Instance count related attributes
    instanceCountAttr = OpenMaya.MObject()
    instancingModeAttr = OpenMaya.MObject()
    instanceLengthAttr = OpenMaya.MObject()
    maxInstancesByLengthAttr = OpenMaya.MObject()

    displayTypeAttr = OpenMaya.MObject()
    bboxAttr = OpenMaya.MObject()

    orientationModeAttr = OpenMaya.MObject()
    inputOrientationAxisAttr = Vector3CompoundAttribute()
    
    inputPositionRandomnessAttr = OpenMaya.MObject()
    inputRotationRandomnessAttr = OpenMaya.MObject()
    inputScaleRandomnessAttr = OpenMaya.MObject()

    # Ramp attributes
    positionRampAttr = OpenMaya.MObject()
    rotationRampAttr = OpenMaya.MObject()
    scaleRampAttr = OpenMaya.MObject()

    rampOffsetAttr = OpenMaya.MObject()

    # Output vectors
    outputTranslationAttr = Vector3CompoundAttribute()
    outputRotationAttr = Vector3CompoundAttribute()
    outputScaleAttr = Vector3CompoundAttribute()

    def __init__(self):
        OpenMayaMPx.MPxLocatorNode.__init__(self)

    def postConstructor(self):
        OpenMaya.MFnDependencyNode(self.thisMObject()).setName("instanceAlongCurveLocatorShape#")

    # Helper function to get an array of available logical indices from the sparse array
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

    def assignShadingGroup(self, fnSet, fnDagNode):
        # Easiest, cleanest way seems to be calling MEL.
        # sets command handles everything, even nested instanced dag paths
        mdgm = OpenMaya.MDGModifier()
        mdgm.commandToExecute("sets -e -fe " + fnSet.name() + " " + fnDagNode.name())
        mdgm.doIt()

    # Find original SG to reassign it to instance
    def getShadingGroup(self):
        inputSGPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputShadingGroupAttr)
        sgNode = self.getSingleSourceObjectFromPlug(inputSGPlug)

        if sgNode is not None and sgNode.hasFn(OpenMaya.MFn.kSet):
            return OpenMaya.MFnSet(sgNode)

        return None

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

    def updateInstanceConnections(self, path):

        # If the locator is being instanced, just stop updating its children.
        # This is to prevent losing references to the locator instances' children
        # If you want to change this locator, prepare the source before instantiating
        if OpenMaya.MFnDagNode(self.thisMObject()).isInstanced():
            return OpenMaya.kUnknownParameter

        expectedInstanceCount = self.getInstanceCountByMode()
        outputTranslationPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.outputTranslationAttr.compound)
        outputRotationPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.outputRotationAttr.compound)    
        numConnectedElements = outputTranslationPlug.numConnectedElements()

        # Only instance if we are missing elements
        # TODO: handle mismatches in translation/rotation plug connected elements (user deleted a plug? use connectionBroken method?)
        if numConnectedElements < expectedInstanceCount:

            inputTransformFn = self.getInputTransformFn()

            if inputTransformFn is not None:

                # Get shading group first
                dagPath = OpenMaya.MDagPath()
                inputTransformFn.getPath(dagPath)
                shadingGroupFn = self.getShadingGroup()

                instanceCount = expectedInstanceCount - numConnectedElements
                availableIndices = self.getAvailableLogicalIndices(outputTranslationPlug, instanceCount)

                # Consider path for instances!
                nodeFn = OpenMaya.MFnDagNode(path.transform())

                displayPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.displayTypeAttr)
                LODPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.bboxAttr)

                mdgModifier = OpenMaya.MDagModifier()

                # Instance as many times as necessary
                for i in availableIndices:
                    
                    # Instance transform
                    # InstanceLeaf must be set to False to prevent crashes :)
                    trInstance = inputTransformFn.duplicate(True, False)
                    instanceFn = OpenMaya.MFnTransform(trInstance)

                    # Parent new instance
                    nodeFn.addChild(trInstance)

                    # Recursively assign shading group
                    if shadingGroupFn is not None:
                        self.assignShadingGroup(shadingGroupFn, OpenMaya.MFnDagNode(trInstance))

                    instanceTranslatePlug = instanceFn.findPlug('translate', False)
                    outputTranslationPlugElement = outputTranslationPlug.elementByLogicalIndex(i)

                    instanceRotationPlug = instanceFn.findPlug('rotate', False)
                    outputRotationPlugElement = outputRotationPlug.elementByLogicalIndex(i)

                    # Enable drawing overrides
                    overrideEnabledPlug = instanceFn.findPlug("overrideEnabled", False)
                    overrideEnabledPlug.setBool(True)

                    instanceDisplayPlug = instanceFn.findPlug("overrideDisplayType", False)
                    instanceLODPlug = instanceFn.findPlug("overrideLevelOfDetail", False)

                    if not outputTranslationPlugElement.isConnected():
                        mdgModifier.connect(outputTranslationPlugElement, instanceTranslatePlug)

                    if not outputRotationPlugElement.isConnected():
                        mdgModifier.connect(outputRotationPlugElement, instanceRotationPlug)

                    if not instanceDisplayPlug.isConnected():
                        mdgModifier.connect(displayPlug, instanceDisplayPlug)

                    if not instanceLODPlug.isConnected():
                        mdgModifier.connect(LODPlug, instanceLODPlug)

                mdgModifier.doIt()

        # Remove instances if necessary
        elif numConnectedElements > expectedInstanceCount:

            connections = OpenMaya.MPlugArray()        
            toRemove = numConnectedElements - expectedInstanceCount

            mdgModifier = OpenMaya.MDGModifier()
            for i in xrange(toRemove):
                outputTranslationPlugElement = outputTranslationPlug.connectionByPhysicalIndex(numConnectedElements - 1 - i)
                outputTranslationPlugElement.connectedTo(connections, False, True)

                print outputTranslationPlugElement.name()
                print str(connections) + ", " +  str(connections.length())
                

                for c in xrange(connections.length()):
                    print connections[c].node().isNull()
                    print "About to disconnect plug " + connections[c].name()
                    print "About to delete node " + OpenMaya.MFnDependencyNode(connections[c].node()).name()
                    mdgModifier.deleteNode(connections[c].node())
                    # mdgModifier.disconnect(outputTranslationPlugElement, connections[c])

            print "About to do it! " + str(mdgModifier)
            mdgModifier.doIt()
            print "Did it!"

    def updateInstancePositions(self, curveFn, dataBlock, count):

            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            translateArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputTranslationAttr.compound)

            randomRadius = dataBlock.outputValue(instanceAlongCurveLocator.inputPositionRandomnessAttr).asFloat()

            # Deterministic random
            random.seed(count)

            # Make sure there are enough handles...
            for i in xrange(min(count, translateArrayHandle.elementCount())):

                param = curveFn.findParamFromLength(curveLength * (i / float(count)))
                curveFn.getPointAtParam(param, point)

                point.x += (random.random() * 2.0 - 1.0) * randomRadius
                point.y += (random.random() * 2.0 - 1.0) * randomRadius
                point.z += (random.random() * 2.0 - 1.0) * randomRadius

                translateArrayHandle.jumpToArrayElement(i)
                translateHandle = translateArrayHandle.outputValue()
                translateHandle.set3Double(point.x, point.y, point.z)

            translateArrayHandle.setAllClean()
            translateArrayHandle.setClean()


    def getRampValueAtPosition(self, ramp, position):

        util = OpenMaya.MScriptUtil()
        util.createFromDouble(0.0)
        valuePtr = util.asFloatPtr()

        ramp.getValueAtPosition(position, valuePtr)

        return util.getFloat(valuePtr)

    def updateInstanceScale(self, curveFn, dataBlock, count):

            point = OpenMaya.MPoint()
            scaleArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputScaleAttr.compound)

            # Deterministic random
            randomScale = dataBlock.outputValue(instanceAlongCurveLocator.inputScaleRandomnessAttr).asFloat()
            random.seed(count)

            scaleRampPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.scaleRampAttr)
            scaleRamp = OpenMaya.MRampAttribute(scaleRampPlug)

            rampOffset = dataBlock.inputValue(instanceAlongCurveLocator.rampOffsetAttr).asFloat()

            # Make sure there are enough handles...
            for i in xrange(min(count, scaleArrayHandle.elementCount())):

                rampPosition = math.fmod((i / float(count)) + rampOffset, 1.0)

                rampValue = self.getRampValueAtPosition(scaleRamp, rampPosition)

                point.x = random.random() * randomScale + rampValue
                point.y = random.random() * randomScale + rampValue
                point.z = random.random() * randomScale + rampValue

                scaleArrayHandle.jumpToArrayElement(i)
                scaleHandle = scaleArrayHandle.outputValue()
                scaleHandle.set3Double(point.x, point.y, point.z)

            scaleArrayHandle.setAllClean()
            scaleArrayHandle.setClean()

    def updateInstanceRotations(self, curveFn, dataBlock, count):
            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            rotationArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputRotationAttr.compound)
            startOrientation = dataBlock.outputValue(instanceAlongCurveLocator.inputOrientationAxisAttr.compound).asVector().normal()

            randomRadius = dataBlock.outputValue(instanceAlongCurveLocator.inputRotationRandomnessAttr).asFloat()
            randomRadius *= 3.141592 / 180.0

            # Deterministic random
            random.seed(count)

            rotMode = dataBlock.inputValue(instanceAlongCurveLocator.orientationModeAttr).asInt()

            inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
            inputTransformRotation = OpenMaya.MQuaternion()

            if inputTransformPlug.isConnected():
                self.getInputTransformFn().getRotation(inputTransformRotation, OpenMaya.MSpace.kWorld)

            for i in xrange(min(count, rotationArrayHandle.elementCount())):

                param = curveFn.findParamFromLength(curveLength * (i / float(count)))
                rot = OpenMaya.MQuaternion()

                if rotMode == 1:
                    rot = inputTransformRotation; # No realtime preview - use an inputRotation for that?
                elif rotMode == 2:
                    normal = curveFn.normal(param)
                    rot = startOrientation.rotateTo(normal)
                elif rotMode == 3:
                    tangent = curveFn.tangent(param)
                    rot = startOrientation.rotateTo(tangent)
                elif rotMode == 4:
                    tangent = curveFn.tangent(param)
                    rot = startOrientation.rotateTo(tangent)
                    
                    if i % 2 == 1:
                        rot *= OpenMaya.MQuaternion(3.141592 * .5, tangent)

                rot = rot.asEulerRotation().asVector()

                rot.x += (random.random() * 2.0 - 1.0) * randomRadius
                rot.y += (random.random() * 2.0 - 1.0) * randomRadius
                rot.z += (random.random() * 2.0 - 1.0) * randomRadius

                rotationArrayHandle.jumpToArrayElement(i)
                rotationHandle = rotationArrayHandle.outputValue()
                rotationHandle.set3Double(rot.x, rot.y, rot.z)

            rotationArrayHandle.setAllClean()
            rotationArrayHandle.setClean()

    def compute(self, plug, dataBlock):
        try:
            timeDataHandle = dataBlock.inputValue( instanceAlongCurveLocator.inputTimeAttr )
            time = timeDataHandle.asTime().value()

            curveDataHandle = dataBlock.inputValue(instanceAlongCurveLocator.inputCurveAttr)
            curve = curveDataHandle.asNurbsCurveTransformed()

            if not curve.isNull():
                curveFn = OpenMaya.MFnNurbsCurve(curve)

                # print "Computing! " + plug.info()

                instanceCount = self.getInstanceCountByMode()

                if plug == instanceAlongCurveLocator.outputTranslationAttr.compound:
                    self.updateInstancePositions(curveFn, dataBlock, instanceCount)

                if plug == instanceAlongCurveLocator.outputRotationAttr.compound:
                    self.updateInstanceRotations(curveFn, dataBlock, instanceCount)

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

    @staticmethod
    def nodeInitializer():

        # To make things more readable
        node = instanceAlongCurveLocator

        nAttr = OpenMaya.MFnNumericAttribute()
        msgAttributeFn = OpenMaya.MFnMessageAttribute()
        curveAttributeFn = OpenMaya.MFnTypedAttribute()
        enumFn = OpenMaya.MFnEnumAttribute()
        matrixFn = OpenMaya.MFnTypedAttribute()
        timeFn = OpenMaya.MFnUnitAttribute()

        node.inputTransformAttr = msgAttributeFn.create("inputTransform", "it")
        node.addAttribute( node.inputTransformAttr )

        node.inputShadingGroupAttr = msgAttributeFn.create("inputShadingGroup", "iSG")    
        node.addAttribute( node.inputShadingGroupAttr )

        # Input time
        node.inputTimeAttr = timeFn.create("inputTime", "inputTime", OpenMaya.MFnUnitAttribute.kTime)
        node.addAttribute( node.inputTimeAttr )

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

        node.inputPositionRandomnessAttr = nAttr.create("inputPositionRandomness", "inputPositionRandomness", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setMin(0.0)
        nAttr.setSoftMax(1.0)
        nAttr.setKeyable( True )
        node.addAttribute( node.inputPositionRandomnessAttr )

        node.inputRotationRandomnessAttr = nAttr.create("inputRotationRandomness", "inputRotationRandomness", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setMin(0.0)
        nAttr.setSoftMax(90.0)
        nAttr.setKeyable( True )
        node.addAttribute( node.inputRotationRandomnessAttr )

        node.inputScaleRandomnessAttr = nAttr.create("inputScaleRandomness", "inputScaleRandomness", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setMin(0.0)
        nAttr.setSoftMax(1.0)
        nAttr.setKeyable( True )
        node.addAttribute( node.inputScaleRandomnessAttr )

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

        node.scaleRampAttr = OpenMaya.MRampAttribute.createCurveRamp("scaleRamp", "scaleRamp")
        node.addAttribute( node.scaleRampAttr )

        node.rampOffsetAttr = nAttr.create("rampOffset", "rampOffset", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setKeyable( True )
        node.addAttribute( node.rampOffsetAttr )

        node.addCompoundVector3Attribute(node.inputOrientationAxisAttr, "inputOrientationAxis", OpenMaya.MFnUnitAttribute.kDistance, False, True, OpenMaya.MVector(0.0, 0.0, 1.0))

        node.bboxAttr = nAttr.create('instanceBoundingBox', 'ibb', OpenMaya.MFnNumericData.kBoolean)
        node.addAttribute( node.bboxAttr )

        # Output attributes
        node.addCompoundVector3Attribute(node.outputTranslationAttr, "outputTranslation", OpenMaya.MFnUnitAttribute.kDistance, True, False, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.outputRotationAttr, "outputRotation", OpenMaya.MFnUnitAttribute.kAngle, True, False, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.outputScaleAttr, "outputScale", OpenMaya.MFnUnitAttribute.kDistance, True, False, OpenMaya.MVector(1.0, 1.0, 1.0))

        # Translation affects
        node.attributeAffects( node.inputTimeAttr, node.outputTranslationAttr.compound )
        node.attributeAffects( node.inputCurveAttr, node.outputTranslationAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.inputPositionRandomnessAttr, node.outputTranslationAttr.compound)

        # Rotation affects
        node.attributeAffects( node.inputTimeAttr, node.outputRotationAttr.compound )
        node.attributeAffects( node.inputCurveAttr, node.outputRotationAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.orientationModeAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.inputRotationRandomnessAttr, node.outputRotationAttr.compound)

        node.attributeAffects( node.inputOrientationAxisAttr.compound, node.outputRotationAttr.compound)

        # Scale affects
        node.attributeAffects( node.inputTimeAttr, node.outputScaleAttr.compound )
        node.attributeAffects( node.inputCurveAttr, node.outputScaleAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.inputScaleRandomnessAttr, node.outputScaleAttr.compound)
    
        node.attributeAffects( node.scaleRampAttr, node.outputScaleAttr.compound)

        # Ramp offset
        node.attributeAffects( node.rampOffsetAttr, node.scaleRampAttr)
        node.attributeAffects( node.rampOffsetAttr, node.outputScaleAttr.compound)
        
def initializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        # Register command
        mplugin.registerCommand( kPluginCmdName, instanceAlongCurveCommand.cmdCreator )

        if OpenMaya.MGlobal.mayaState() != OpenMaya.MGlobal.kBatch:
            mplugin.addMenuItem("Instance Along Curve", "MayaWindow|mainEditMenu", kPluginCmdName, "")

            # Register AE template
            pm.callbacks(addCallback=loadAETemplateCallback, hook='AETemplateCustomContent', owner=kPluginNodeName)

        # Register node
        mplugin.registerNode( kPluginNodeName, kPluginNodeId, instanceAlongCurveLocator.nodeCreator,
                              instanceAlongCurveLocator.nodeInitializer, OpenMayaMPx.MPxNode.kLocatorNode, kPluginNodeClassify )
    except:
        sys.stderr.write('Failed to register plugin instanceAlongCurve. stack trace: \n')
        sys.stderr.write(traceback.format_exc())
        raise
    
def uninitializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        mplugin.deregisterCommand( kPluginCmdName )
        mplugin.deregisterNode( kPluginNodeId )
    except:
        sys.stderr.write( 'Failed to deregister plugin instanceAlongCurve')
        raise

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
            self.beginLayout("Instance Along Curve Settings" ,collapse=0)

            self.addControl("instancingMode", label="Instancing Mode", changeCommand=self.onInstanceModeChanged)
            self.addControl("instanceCount", label="Count", changeCommand=self.onInstanceCountChanged)
            self.addControl("instanceLength", label="Distance", changeCommand=self.onInstanceCountChanged)
            self.addControl("maxInstancesByLength", label="Max Instances", changeCommand=self.onInstanceCountChanged)

            self.callCustom(self.onControlBuild, self.onControlUpdate, "instancingMode")
            
            self.addSeparator()

            self.addControl("orientationMode", label="Orientation Mode")
            self.addControl("inputOrientationAxis", label="Orientation Axis")

            self.addSeparator()

            mel.eval('AEaddRampControl("' + nodeName + '.scaleRamp"); ')

            self.addControl("rampOffset", label="Ramp offset")

            self.addSeparator()

            self.addControl("inputPositionRandomness", label="Position random")
            self.addControl("inputRotationRandomness", label="Rotation random (angle)")
            self.addControl("inputScaleRandomness", label="Scale random")

            self.addSeparator()
            
            self.addControl("instanceDisplayType", label="Instance Display Type")
            self.addControl("instanceBoundingBox", label="Use bounding box")
            
            self.addSeparator()
            
            self.addControl("inputTransform", label="Input object")
            self.addControl("inputShadingGroup", label="Shading Group")
            self.addExtraControls()

            self.endLayout()
            self.endScrollLayout()

    def onRampUpdate(self, attr):
        print attr
        pm.gradientControl(attr)

    def onControlUpdate(self, attr):
        None
        # expectedCount = self.getExpectedCount(self.node)
        # pm.text("Expected count: " + str(expectedCount))

    def onControlBuild(self, attr):
        # pm.button(label="Update").setCommand(self.onUpdateButtonPressed)
        None

    def onUpdateButtonPressed(self, *args):        
        None

    def getExpectedCount(self, node):
        mode = node.instancingMode.get()
        
        if node.inputCurve.isConnected() and mode == 1:
            instanceLength = node.instanceLength.get()
            maxInstancesByLength = node.maxInstancesByLength.get()
            curveLength = pm.PyNode(node.inputCurve.inputs()[0]).length()
            return min(maxInstancesByLength, int(curveLength / instanceLength))

        # InstanceCount attr conflicts with pymel method
        return node.attr("instanceCount").get()

    def onInstanceCountChanged(self, nodeName):
        if pm.PyNode(nodeName).type() == kPluginNodeName:

            node = pm.PyNode(nodeName)
            expectedCount = self.getExpectedCount(node)
            connectedElements = node.outputTranslation.numConnectedElements()

            # Only instance if we are missing elements
            if connectedElements < expectedCount:

                if node.inputTransform.isConnected():

                    inputTransform = pm.PyNode(node.inputTransform.inputs()[0])
                    instanceCount = expectedCount - connectedElements

                    instances = []

                    for i in xrange(instanceCount):

                        instance = pm.instance(inputTransform, leaf = False)[0]

                        # Parent instance to transform node
                        transformNode = node.getParent()
                        transformNode.addChild(instance)

                        # Transformation connections
                        node.outputTranslation[connectedElements + i].connect(instance.translate)
                        node.outputRotation[connectedElements + i].connect(instance.rotate)
                        node.outputScale[connectedElements + i].connect(instance.scale)

                        # Overrides
                        instance.overrideEnabled.set(True)
                        node.instanceDisplayType.connect(instance.overrideDisplayType)
                        node.instanceBoundingBox.connect(instance.overrideLevelOfDetail)

                        instances.append(instance)

                    # Assign shading group to all instances
                    pm.sets(node.inputShadingGroup.get(), forceElement=instances)

                    # For some reason it seems to lose focus, so reselect!
                    pm.select(node)
            else:
                
                connections = node.outputTranslation.outputs()
                toRemove = connectedElements - expectedCount

                for i in xrange(toRemove):
                    element = node.outputTranslation[connectedElements - 1 - i]
                    pm.delete(element.outputs()[0])

    def onInstanceModeChanged(self, nodeName):
        if pm.PyNode(nodeName).type() == kPluginNodeName:

            self.onInstanceCountChanged(nodeName)

            nodeAttr = pm.PyNode(nodeName + ".instancingMode")
            mode = nodeAttr.get("instancingMode")
            self.dimControl(nodeName, "instanceLength", mode == 0)
            self.dimControl(nodeName, "maxInstancesByLength", mode == 0)
            self.dimControl(nodeName, "instanceCount", mode == 1)
            # TODO: dim everything if there is no curve or transform

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

                    # Get the node shape
                    nodeShapeDagPath = OpenMaya.MDagPath()
                    newNodeFn.getPath(nodeShapeDagPath)
                    nodeShapeDagPath.extendToShape()
                    newNodeFn = OpenMaya.MFnDagNode(nodeShapeDagPath)

                    # Set default ramp values
                    defaultPositions = OpenMaya.MFloatArray(1, 0.0)
                    defaultValues = OpenMaya.MFloatArray(1, 1.0)
                    defaultInterpolations = OpenMaya.MIntArray(1, 3)

                    scaleRampPlug = newNodeFn.findPlug(instanceAlongCurveLocator.scaleRampAttr)
                    scaleRamp = OpenMaya.MRampAttribute(scaleRampPlug)
                    scaleRamp.addEntries(defaultPositions, defaultValues, defaultInterpolations)

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