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

kPluginVersion = "1.1.0"
kPluginCmdName = "instanceAlongCurve"
kPluginCtxCmdName = "instanceAlongCurveCtx"
kPluginNodeName = 'instanceAlongCurveLocator'
kPluginManipNodeName = 'instanceAlongCurveLocatorManip'
kPluginNodeClassify = 'utility/general'
kPluginNodeId = OpenMaya.MTypeId( 0x55555 ) 
kPluginNodeManipId = OpenMaya.MTypeId( 0x55556 ) 

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
            self.angle = OpenMaya.MObject() # The angle over the tangent axis

    # Input attributes
    inputCurveAttr = OpenMaya.MObject()
    inputTransformAttr = OpenMaya.MObject()
    inputShadingGroupAttr = OpenMaya.MObject()

    # Translation offsets
    inputLocalTranslationOffsetAttr = OpenMaya.MObject()
    inputGlobalTranslationOffsetAttr = OpenMaya.MObject()

    # Rotation offsets
    inputLocalRotationOffsetAttr = OpenMaya.MObject()
    inputGlobalRotationOffsetAttr = OpenMaya.MObject()

    # Instance count related attributes
    instanceCountAttr = OpenMaya.MObject()
    instancingModeAttr = OpenMaya.MObject()
    instanceLengthAttr = OpenMaya.MObject()
    maxInstancesByLengthAttr = OpenMaya.MObject()

    # Curve axis data, to be manipulated by user
    enableManipulatorsAttr = OpenMaya.MObject()
    curveAxisHandleAttr = CurveAxisHandleAttribute()
    curveAxisHandleCountAttr = OpenMaya.MObject()

    displayTypeAttr = OpenMaya.MObject()
    bboxAttr = OpenMaya.MObject()

    orientationModeAttr = OpenMaya.MObject()
    inputLocalOrientationAxisAttr = OpenMaya.MObject()

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
        sgNode = getSingleSourceObjectFromPlug(inputSGPlug)

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

                rotatePivot = inputTransformFn.rotatePivotTranslation(OpenMaya.MSpace.kObject)

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

                    instanceFn.setRotatePivotTranslation(rotatePivot, OpenMaya.MSpace.kObject)

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

    def getInputTransformFn(self):
        inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
        transform = getSingleSourceObjectFromPlug(inputTransformPlug)

        # Get Fn from a DAG path to get the world transformations correctly
        if transform is not None and transform.hasFn(OpenMaya.MFn.kTransform):
                path = OpenMaya.MDagPath()
                trFn = OpenMaya.MFnDagNode(transform)
                trFn.getPath(path)
                return OpenMaya.MFnTransform(path)

        return None

    def getCurveFn(self):
        inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)
        curve = getSingleSourceObjectFromPlug(inputCurvePlug)

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

    def getRandomizedValue(self, random, randomAmplitude, value):
        return (random.random() * 2.0 - 1.0) * randomAmplitude + value

    def updateInstancePositions(self, curveFn, dataBlock, count, distOffset ):

            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            maxParam = curveFn.findParamFromLength(curveFn.length())
            translateArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputTranslationAttr.compound)

            # rotMode = dataBlock.inputValue(instanceAlongCurveLocator.orientationModeAttr).asInt()            
            curveAxisHandleArray = dataBlock.inputArrayValue(instanceAlongCurveLocator.curveAxisHandleAttr.compound)
            axisHandlesSorted = getSortedCurveAxisArray(self.thisMObject(), curveAxisHandleArray, count)

            localTranslationOffset = dataBlock.outputValue(instanceAlongCurveLocator.inputLocalTranslationOffsetAttr.compound).asVector()
            globalTranslationOffset = dataBlock.outputValue(instanceAlongCurveLocator.inputGlobalTranslationOffsetAttr.compound).asVector()
            
            inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)

            # Get pivot
            rotatePivot = OpenMaya.MVector()
            if inputTransformPlug.isConnected():
                rotatePivot = OpenMaya.MVector(self.getInputTransformFn().rotatePivot(OpenMaya.MSpace.kObject))

            # Deterministic random
            random.seed(count)
            rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.positionRampAttr, False)

            # Make sure there are enough handles...
            for i in xrange(min(count, translateArrayHandle.elementCount())):

                rampValue = self.getRampValueAtPosition(rampValues, i, count)
                dist = math.fmod(curveLength * (i / float(count)) + distOffset, curveLength)

                # EP curves **really** dont like param at 0.0 
                param = max( min( curveFn.findParamFromLength( dist ), maxParam ), 0)
                curveFn.getPointAtParam(param, point)

                # tangent = curveFn.tangent(param)

                # rot = startOrientation.rotateTo(tangent)

                # try:
                #     normal = curveFn.normal(param).normal()
                #     tangent = curveFn.tangent(param).normal()
                #     bitangent = (normal ^ tangent).normal()
                # except:
                #     # If base cannot be computed, fallback to identity rotation.
                #     # This seems to be a bug in the API...
                #     normal = OpenMaya.MVector(0.0, 1.0, 0.0)
                #     tangent = OpenMaya.MVector(0.0, 0.0, 1.0)
                #     bitangent = OpenMaya.MVector(1.0, 0.0, 0.0)

                # if rotMode == 5:
                #     rot = getRotationForParam(param, axisHandlesSorted, curveFn.form(), curveFn.findParamFromLength(curveFn.length()))
                #     normal = normal.rotateBy(rot)
                #     tangent = tangent.rotateBy(rot) 
                #     bitangent = bitangent.rotateBy(rot)

                # twistNormal = normal * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.x
                # twistBitangent = bitangent * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.y
                # twistTangent = tangent * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.z

                # point += twistNormal + twistTangent + twistBitangent

                point += globalTranslationOffset - rotatePivot

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

    # TODO: cache this data to prevent recalculating when there is no manipulator being updated
    def getRotationForParam(self, param, axisHandlesSorted, curveForm, curveMaxParam):

        indexRange = (-1, -1)
        wrapAround = not (curveForm is OpenMaya.MFnNurbsCurve.kOpen)

        # Find the range of indices that make up this curve segment
        for i in xrange(len(axisHandlesSorted)):

            # TODO: could use a binary search
            if param < axisHandlesSorted[i][1]:

                if i > 0:
                    indexRange = (i - 1, i)
                    break
                elif wrapAround:
                    indexRange = (len(axisHandlesSorted) - 1, 0)
                    break
                else:
                    indexRange = (0, 0)
                    break

        # Edge case
        if indexRange[0] == -1 and indexRange[1] == -1 and len(axisHandlesSorted) > 0:
            if wrapAround:
                indexRange = (len(axisHandlesSorted) - 1, 0)
            else:
                indexRange = (len(axisHandlesSorted) - 1, len(axisHandlesSorted) - 1)
            
        # Now find the lerp value based on the range
        if indexRange[0] > -1 and indexRange[1] > -1:
            minParam = axisHandlesSorted[indexRange[0]][1]
            maxParam = axisHandlesSorted[indexRange[1]][1]

            minAxis = axisHandlesSorted[indexRange[0]][2]
            maxAxis = axisHandlesSorted[indexRange[1]][2]

            if(math.fabs(minParam - maxParam) > 0.001):

                if minParam > maxParam and wrapAround:

                    if param < maxParam:
                        param = param + curveMaxParam

                    maxParam = maxParam + curveMaxParam
                
                t = min(max((param - minParam) / (maxParam - minParam), 0.0), 1.0)

                return minAxis + (maxAxis - minAxis) * t

            return minAxis

        return 0.0

    def updateInstanceRotations(self, curveFn, dataBlock, count, distOffset ):
        point = OpenMaya.MPoint()
        curveLength = curveFn.length()
        rotationArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputRotationAttr.compound)

        # All offsets are in degrees
        localRotationOffset = dataBlock.inputValue(instanceAlongCurveLocator.inputLocalRotationOffsetAttr.compound).asVector() * math.radians(1)
        globalRotationOffset = dataBlock.inputValue(instanceAlongCurveLocator.inputGlobalRotationOffsetAttr.compound).asVector() * math.radians(1)

        localRotationOffset = OpenMaya.MEulerRotation(localRotationOffset.x, localRotationOffset.y, localRotationOffset.z).asQuaternion()
        globalRotationOffset = OpenMaya.MEulerRotation(globalRotationOffset.x, globalRotationOffset.y, globalRotationOffset.z).asQuaternion()

        # Important: enums are short! If not, the resulting int may be incorrect
        rotMode = dataBlock.inputValue(instanceAlongCurveLocator.orientationModeAttr).asShort()
        localRotationAxisMode = dataBlock.inputValue(instanceAlongCurveLocator.inputLocalOrientationAxisAttr).asShort()

        if localRotationAxisMode == 0:
            forward = OpenMaya.MVector.xAxis
            up = OpenMaya.MVector.yAxis
            right = OpenMaya.MVector.zAxis
        elif localRotationAxisMode == 1:
            forward = OpenMaya.MVector.yAxis
            up = OpenMaya.MVector.zAxis
            right = OpenMaya.MVector.xAxis
        elif localRotationAxisMode == 2:
            forward = OpenMaya.MVector.zAxis
            up = OpenMaya.MVector.yAxis
            right = OpenMaya.MVector.xAxis

        # We use Z axis as forward, and adjust locally to that axis
        referenceAxis = OpenMaya.MVector.zAxis
        referenceUp = OpenMaya.MVector.yAxis
        localRotation = localRotationOffset.inverse() * referenceAxis.rotateTo(forward)

        # Deterministic random
        random.seed(count)
        rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.rotationRampAttr, True)

        # Manipulator stuff
        curveAxisHandleArray = dataBlock.inputArrayValue(instanceAlongCurveLocator.curveAxisHandleAttr.compound)
        axisHandlesSorted = getSortedCurveAxisArray(self.thisMObject(), curveAxisHandleArray, count)

        # Original transform data
        inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
        inputTransformRotation = OpenMaya.MQuaternion()

        maxParam = curveFn.findParamFromLength(curveFn.length())
        curveForm = curveFn.form()

        enableManipulators = dataBlock.inputValue(instanceAlongCurveLocator.enableManipulatorsAttr).asBool()

        # First, map parameter
        if inputTransformPlug.isConnected():
            self.getInputTransformFn().getRotation(inputTransformRotation, OpenMaya.MSpace.kWorld)

        for i in xrange(min(count, rotationArrayHandle.elementCount())):

            rampValue = self.getRampValueAtPosition(rampValues, i, count)
            dist = math.fmod(curveLength * (i / float(count)) + distOffset, curveLength)
            param = max( min( curveFn.findParamFromLength( dist ), maxParam ), 0.0)

            tangent = curveFn.tangent(param)
            rot = referenceAxis.rotateTo(tangent)

            # If the axis is parallel, but with inverse direction, rotate it PI over the up vector
            if referenceAxis.isParallel(tangent) and (referenceAxis * tangent < 0):
                rot = OpenMaya.MQuaternion(math.pi, referenceUp)

            # Transform rotation so that it is aligned with the tangent. This fixes unintentional twisting
            rot = localRotation * rot
            
            # The curve basis used for twisting
            basisForward = tangent
            basisUp = up.rotateBy(rot)
            basisRight = right.rotateBy(rot)

            twistNormal = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.x                
            twistNormal = OpenMaya.MQuaternion(math.radians(twistNormal), basisRight) #X

            twistTangent = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.y
            twistTangent = OpenMaya.MQuaternion(math.radians(twistTangent), basisUp) #Y

            twistBitangent = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampValues.rampAmplitude) * rampValues.rampAxis.z
            twistBitangent = OpenMaya.MQuaternion(math.radians(twistBitangent), basisForward) #Z

            # Modify resulting rotation based on mode
            if rotMode == 0:                    # Identity
                rot = OpenMaya.MQuaternion()
            elif rotMode == 1:                  # Input rotation
                rot = inputTransformRotation;
            elif rotMode == 3 and i % 2 == 1:   # Chain mode
                rot *= OpenMaya.MQuaternion(math.pi * .5, tangent)

            # Get the angle from handles, and rotate over tangent axis
            if enableManipulators:
                angle = self.getRotationForParam(param, axisHandlesSorted, curveForm, maxParam)
                rot = rot * OpenMaya.MQuaternion(-angle, tangent)

            rot = ((rot * twistNormal * twistTangent * twistBitangent) * globalRotationOffset).asEulerRotation().asVector()

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
                distOffset = dataBlock.inputValue(instanceAlongCurveLocator.distOffsetAttr).asFloat()

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
        #   curveAxisHandleAngle

        nAttr = OpenMaya.MFnNumericAttribute()
        cmpAttr = OpenMaya.MFnCompoundAttribute()

        curveAxisHandleAttr.parameter = nAttr.create(attributeName + "Parameter", attributeName + "Parameter", OpenMaya.MFnNumericData.kDouble, 0.0)
        nAttr.setWritable( True )
        cls.addAttribute(curveAxisHandleAttr.parameter)

        curveAxisHandleAttr.angle = nAttr.create(attributeName + "Angle", attributeName + "Angle", OpenMaya.MFnNumericData.kDouble, 0.0)
        nAttr.setWritable( True )
        cls.addAttribute(curveAxisHandleAttr.angle)

        # cls.addCompoundVector3Attribute(curveAxisHandleAttr.axis, attributeName + "Axis", OpenMaya.MFnUnitAttribute.kAngle, False, True, defaultAxisValue)

        # Build compound array attribute
        curveAxisHandleAttr.compound = cmpAttr.create(attributeName, attributeName)
        cmpAttr.addChild(curveAxisHandleAttr.parameter)
        cmpAttr.addChild(curveAxisHandleAttr.angle)
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

        node.addCompoundVector3Attribute(node.inputLocalRotationOffsetAttr, "inputLocalRotationOffset", OpenMaya.MFnUnitAttribute.kDistance, False, True, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.inputGlobalRotationOffsetAttr, "inputGlobalRotationOffset", OpenMaya.MFnUnitAttribute.kDistance, False, True, OpenMaya.MVector(0.0, 0.0, 0.0))

        node.addCompoundVector3Attribute(node.inputGlobalTranslationOffsetAttr, "inputGlobalTranslationOffset", OpenMaya.MFnUnitAttribute.kDistance, False, True, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.inputLocalTranslationOffsetAttr, "inputLocalTranslationOffset", OpenMaya.MFnUnitAttribute.kDistance, False, True, OpenMaya.MVector(0.0, 0.0, 0.0))

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
        node.orientationModeAttr = enumFn.create('orientationMode', 'orientationMode')
        enumFn.addField( "Identity", 0 );
        enumFn.addField( "Copy from Source", 1 );
        enumFn.addField( "Use Curve", 2 );
        enumFn.addField( "Chain", 3 );
        enumFn.setDefault("Use Curve")
        node.addAttribute( node.orientationModeAttr )

        node.inputLocalOrientationAxisAttr = enumFn.create('inputLocalOrientationAxis', 'inputLocalOrientationAxis')
        enumFn.addField("X", 0)
        enumFn.addField("Y", 1)
        enumFn.addField("Z", 2)
        enumFn.setDefault("Z")
        node.addAttribute( node.inputLocalOrientationAxisAttr )

        node.bboxAttr = nAttr.create('instanceBoundingBox', 'ibb', OpenMaya.MFnNumericData.kBoolean)
        node.addAttribute( node.bboxAttr )

        node.addRampAttributes(node.positionRampAttr, "position", OpenMaya.MFnUnitAttribute.kDistance, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addRampAttributes(node.rotationRampAttr, "rotation", OpenMaya.MFnUnitAttribute.kAngle, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addRampAttributes(node.scaleRampAttr, "scale", OpenMaya.MFnUnitAttribute.kDistance, OpenMaya.MVector(1.0, 1.0, 1.0))

        # Output attributes
        node.addCompoundVector3Attribute(node.outputTranslationAttr, "outputTranslation", OpenMaya.MFnUnitAttribute.kDistance, True, False, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.outputRotationAttr, "outputRotation", OpenMaya.MFnUnitAttribute.kAngle, True, False, OpenMaya.MVector(0.0, 0.0, 0.0))
        node.addCompoundVector3Attribute(node.outputScaleAttr, "outputScale", OpenMaya.MFnUnitAttribute.kDistance, True, False, OpenMaya.MVector(1.0, 1.0, 1.0))

        ## Input instance count    
        node.enableManipulatorsAttr = nAttr.create("enableManipulators", "enableManipulators", OpenMaya.MFnNumericData.kBoolean)
        node.addAttribute( node.enableManipulatorsAttr)

        node.addCurveAxisHandleAttribute(node.curveAxisHandleAttr, "curveAxisHandle", OpenMaya.MVector(0.0,0.0,0.0))

        ## Input handle count
        node.curveAxisHandleCountAttr = nAttr.create("curveAxisHandleCount", "curveAxisHandleCount", OpenMaya.MFnNumericData.kInt, 5)
        nAttr.setMin(1)
        nAttr.setSoftMax(100)
        nAttr.setChannelBox( False )
        nAttr.setConnectable( False )
        node.addAttribute( node.curveAxisHandleCountAttr)

        def rampAttributeAffects(rampAttributes, affectedAttr):
            node.attributeAffects( rampAttributes.ramp, affectedAttr)
            node.attributeAffects( rampAttributes.rampOffset, affectedAttr)
            node.attributeAffects( rampAttributes.rampAmplitude, affectedAttr)
            node.attributeAffects( rampAttributes.rampAxis.compound, affectedAttr)
            node.attributeAffects( rampAttributes.rampRandomAmplitude, affectedAttr)

        # Curve Axis affects, for manipulator
        node.attributeAffects( node.inputCurveAttr, node.curveAxisHandleAttr.compound )
        node.attributeAffects( node.curveAxisHandleCountAttr, node.curveAxisHandleAttr.compound )

        # Translation affects
        node.attributeAffects( node.inputCurveAttr, node.outputTranslationAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.distOffsetAttr, node.outputTranslationAttr.compound )
        node.attributeAffects( node.inputTransformAttr, node.outputTranslationAttr.compound )

        node.attributeAffects( node.inputLocalOrientationAxisAttr, node.outputTranslationAttr.compound)

        node.attributeAffects(node.inputLocalTranslationOffsetAttr.compound, node.outputTranslationAttr.compound )
        node.attributeAffects(node.inputGlobalTranslationOffsetAttr.compound, node.outputTranslationAttr.compound )

        node.attributeAffects( node.enableManipulatorsAttr, node.outputTranslationAttr.compound)
        node.attributeAffects( node.curveAxisHandleAttr.compound, node.outputTranslationAttr.compound)

        rampAttributeAffects(node.positionRampAttr, node.outputTranslationAttr.compound)

        # Rotation affects
        node.attributeAffects( node.inputCurveAttr, node.outputRotationAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.orientationModeAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.distOffsetAttr, node.outputRotationAttr.compound )
        node.attributeAffects( node.inputTransformAttr, node.outputRotationAttr.compound )

        node.attributeAffects( node.inputLocalOrientationAxisAttr, node.outputRotationAttr.compound)
        
        node.attributeAffects( node.enableManipulatorsAttr, node.outputRotationAttr.compound)
        node.attributeAffects( node.curveAxisHandleAttr.compound, node.outputRotationAttr.compound)

        node.attributeAffects( node.inputGlobalRotationOffsetAttr.compound, node.outputRotationAttr.compound)
        node.attributeAffects( node.inputLocalRotationOffsetAttr.compound, node.outputRotationAttr.compound)        

        rampAttributeAffects(node.rotationRampAttr, node.outputRotationAttr.compound)

        # Scale affects
        node.attributeAffects( node.inputCurveAttr, node.outputScaleAttr.compound )
        node.attributeAffects( node.instanceCountAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.instanceLengthAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.instancingModeAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.maxInstancesByLengthAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.distOffsetAttr, node.outputScaleAttr.compound )
        node.attributeAffects( node.inputTransformAttr, node.outputScaleAttr.compound )

        node.attributeAffects( node.inputLocalOrientationAxisAttr, node.outputScaleAttr.compound)
        
        node.attributeAffects( node.enableManipulatorsAttr, node.outputScaleAttr.compound)
        node.attributeAffects( node.curveAxisHandleAttr.compound, node.outputScaleAttr.compound)

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

            # Base controls
            self.addControl("instancingMode", label="Instancing Mode", changeCommand=self.onInstanceModeChanged)
            self.addControl("instanceCount", label="Count", changeCommand=self.onInstanceModeChanged)
            self.addControl("instanceLength", label="Distance", changeCommand=self.onInstanceModeChanged)
            self.addControl("maxInstancesByLength", label="Max Instances", changeCommand=self.onInstanceModeChanged)

            self.addSeparator()

            self.addControl("distOffset", label="Curve Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "distOffset"))

            self.addSeparator()

            # Orientation controls            
            self.addControl("orientationMode", label="Orientation Mode", changeCommand=lambda nodeName: self.updateOrientationChange(nodeName))
            self.addControl("inputLocalOrientationAxis", label="Local Axis" , changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputLocalOrientationAxis"))

            self.addSeparator()

            # Manipulator controls
            self.addControl("enableManipulators", label="Enable manipulators", changeCommand=lambda nodeName: self.updateManipCountDimming(nodeName))
            self.addControl("curveAxisHandleCount", label="Manipulator count", changeCommand=lambda nodeName: self.updateManipCountDimming(nodeName))            
            self.callCustom(lambda attr: self.buttonNew(nodeName), lambda attr: None, "curveAxisHandleCount")

            self.addSeparator()

            # Instance look controls
            self.addControl("instanceDisplayType", label="Instance Display Type", changeCommand=lambda nodeName: self.updateDimming(nodeName, "instanceDisplayType"))
            self.addControl("instanceBoundingBox", label="Use bounding box", changeCommand=lambda nodeName: self.updateDimming(nodeName, "instanceBoundingBox"))
            
            self.addSeparator()
            
            # Additional info
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

            self.beginLayout("Offsets", collapse=True)

            self.addControl("inputLocalTranslationOffset", label="Local Translation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputLocalTranslationOffset"))
            self.addControl("inputGlobalTranslationOffset", label="Global Translation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputGlobalTranslationOffset"))

            self.addControl("inputLocalRotationOffset", label="Local Rotation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputLocalRotationOffset"))
            self.addControl("inputGlobalRotationOffset", label="Global Rotation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputGlobalRotationOffset"))
            
            self.endLayout()

            showRampControls("position")
            showRampControls("rotation")
            showRampControls("scale")
            
            self.addExtraControls()

            self.endLayout()
            self.endScrollLayout()

    def buttonNew(self, nodeName):

        # pm.separator( height=5, style='none')
        pm.rowLayout(numberOfColumns=3, adjustableColumn=1, columnWidth3=(80, 100, 100))
        updateManipButton = pm.button( label='Edit Manipulators...', command=lambda *args: self.onEditManipulators(nodeName))

        pm.button( label='Reset Positions', command=lambda *args: self.onResetManipPositions(nodeName))
        pm.button( label='Reset Angles', command=lambda *args: self.onResetManipAngles(nodeName))
    
    def onResetManipPositions(self, nodeName):

        # First, show manips to update manip count
        self.onEditManipulators(nodeName)
        res = pm.confirmDialog( title='Confirm reset positions', message='Are you sure you want to reset the manipulators positions?', button=['Yes','No'], defaultButton='Yes', cancelButton='No', dismissString='No' )

        if res == "Yes":

            pm.select( clear=True )

            node = pm.PyNode(nodeName)
            curve = node.inputCurve
            handles = node.curveAxisHandle

            if len(curve.connections()) == 1:

                curveNode = curve.connections()[0]
                maxParam = curveNode.findParamFromLength(curveNode.length())

                count = min(node.curveAxisHandleCount.get(), handles.numElements())

                index = 0
                for h in handles:
                    if index < count:
                        h.children()[0].set(index * maxParam / float(count))
                        index = index + 1
                        
                pm.select(nodeName)
                pm.runtime.ShowManipulators()

    def onResetManipAngles(self, nodeName):
        
        # First, show manips to update manip count
        self.onEditManipulators(nodeName)
        res = pm.confirmDialog( title='Confirm reset angles', message='Are you sure you want to reset the manipulators angles?', button=['Yes','No'], defaultButton='Yes', cancelButton='No', dismissString='No' )

        if res == "Yes":

            pm.select( clear=True )

            node = pm.PyNode(nodeName)
            handles = node.curveAxisHandle
            count = min(node.curveAxisHandleCount.get(), handles.numElements())

            index = 0
            for h in handles:
                if index < count:
                    h.children()[1].set(0.0)
                    index = index + 1

            pm.select(nodeName)
            pm.runtime.ShowManipulators()

    def onEditManipulators(self, nodeName):
        
        # Unselect first, to trigger rebuilding of manips
        pm.select( clear=True )
        pm.select(nodeName)

        pm.runtime.ShowManipulators()

    # When orientation changes, update related controls...  
    def updateOrientationChange(self, nodeName):
        self.updateDimming(nodeName, "orientationMode")
        self.updateManipCountDimming(nodeName)

    def onRampUpdate(self, attr):
        pm.gradientControl(attr)

    def updateManipCountDimming(self, nodeName):
        self.updateDimming(nodeName, "curveAxisHandleCount", pm.PyNode(nodeName).enableManipulators.get())

    def updateDimming(self, nodeName, attr, additionalCondition = True):

        if pm.PyNode(nodeName).type() == kPluginNodeName:

            node = pm.PyNode(nodeName)
            instanced = node.isInstanced()
            hasInputTransform = node.inputTransform.isConnected()
            hasInputCurve = node.inputCurve.isConnected()

            self.dimControl(nodeName, attr, instanced or (not hasInputCurve) or (not hasInputTransform) or (not additionalCondition))

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

                    rotX = transformFn.findPlug("rotateX", False).asMAngle().asDegrees()
                    rotY = transformFn.findPlug("rotateY", False).asMAngle().asDegrees()
                    rotZ = transformFn.findPlug("rotateZ", False).asMAngle().asDegrees()

                    plugOffsetX = newNodeFn.findPlug("inputLocalRotationOffsetX", False)
                    plugOffsetY = newNodeFn.findPlug("inputLocalRotationOffsetY", False)
                    plugOffsetZ = newNodeFn.findPlug("inputLocalRotationOffsetZ", False)

                    plugOffsetX.setDouble(rotX)
                    plugOffsetY.setDouble(rotY)
                    plugOffsetZ.setDouble(rotZ)

                    
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

        # List of tuples
        self.manipCount = 0
        self.manipHandleList = []
        self.manipIndexCallbacks = {}

        selectedObjects = OpenMaya.MSelectionList()
        OpenMaya.MGlobal.getActiveSelectionList(selectedObjects)

        # Because we need to know the selected object to manipulate, we cannot manipulate various nodes at once...
        if selectedObjects.length() != 1:
            return None

        dagPath = OpenMaya.MDagPath()
        selectedObjects.getDagPath(0, dagPath)
        dagPath.extendToShape()

        nodeFn = OpenMaya.MFnDependencyNode(dagPath.node())
        enableManipulators = nodeFn.findPlug(instanceAlongCurveLocator.enableManipulatorsAttr).asBool()

        # If the node is not using the custom rotation, prevent the user from breaking it ;)
        if not enableManipulators:
            return None

        self.manipCount = nodeFn.findPlug(instanceAlongCurveLocator.curveAxisHandleCountAttr).asInt()

        for i in xrange(self.manipCount):
            pointOnCurveManip = self.addPointOnCurveManip("pointCurveManip" + str(i), "pointCurve" + str(i))
            discManip = self.addDiscManip("discManip" + str(i), "disc" + str(i))
            self.manipHandleList.append((pointOnCurveManip, discManip))

    def getSortedCurveAxisArrayFromPlug(self, nodeFn, count):

        axisHandles = []
        plugArray = nodeFn.findPlug(instanceAlongCurveLocator.curveAxisHandleAttr.compound)

        for i in xrange(count):
            plug = plugArray.elementByLogicalIndex(i)
            parameterPlug = plug.child(instanceAlongCurveLocator.curveAxisHandleAttr.parameter)
            anglePlug = plug.child(instanceAlongCurveLocator.curveAxisHandleAttr.angle)

            axisHandles.append((i, parameterPlug.asDouble(), anglePlug.asDouble()))

        def getKey(item):
            return item[1]

        return sorted(axisHandles, key=getKey)

    def connectToDependNode(self, node):

        try:
            self.nodeFn = OpenMaya.MFnDependencyNode(node)
            curvePlug = self.nodeFn.findPlug(instanceAlongCurveLocator.inputCurveAttr)        
            curveAxisHandleArrayPlug = self.nodeFn.findPlug(instanceAlongCurveLocator.curveAxisHandleAttr.compound)

            self.curveFn = OpenMaya.MFnNurbsCurve(getFnFromPlug(curvePlug, OpenMaya.MFn.kNurbsCurve))
            maxParam = self.curveFn.findParamFromLength(self.curveFn.length())

            if self.manipCount == 0:
                return None

            handleCountPlug = self.nodeFn.findPlug(instanceAlongCurveLocator.curveAxisHandleCountAttr)
            expectedHandleCount = handleCountPlug.asInt()
            actualHandleCount = curveAxisHandleArrayPlug.numElements()
            axisHandlesSorted = self.getSortedCurveAxisArrayFromPlug(self.nodeFn, actualHandleCount)

            # Amount of new handles
            handlesToInit = self.manipCount - actualHandleCount
            handlesPerSegment = 0

            if actualHandleCount > 0:
                handlesPerSegment = max(math.ceil(handlesToInit / float(actualHandleCount)), 1)

            # Build and connect all plugs
            # Note: Previous plugs are still with remnant values (newHandleCount < oldHandleCount),
            # but because when interpolating we just read the handle count attr, it works.
            for i in xrange(self.manipCount):

                # Handle data
                curveAxisHandlePlug = curveAxisHandleArrayPlug.elementByLogicalIndex(i)
                curveParameterPlug = curveAxisHandlePlug.child(instanceAlongCurveLocator.curveAxisHandleAttr.parameter)
                curveAnglePlug = curveAxisHandlePlug.child(instanceAlongCurveLocator.curveAxisHandleAttr.angle)

                fnCurvePoint = OpenMayaUI.MFnPointOnCurveManip(self.manipHandleList[i][0])
                fnCurvePoint.connectToCurvePlug(curvePlug)
                fnCurvePoint.connectToParamPlug(curveParameterPlug)
                
                # If we are adding a new handle, we should initialize this handle to some reasonable param/rotation
                # Otherwise, just keep the previous handle data... it seems the most usable solution
                if i >= actualHandleCount:

                    if actualHandleCount > 1:

                        # We distribute these new handles over existing segments, so try to distribute them evenly
                        handleSegmentIndex = (i - actualHandleCount) % actualHandleCount
                        handleEndSegmendIndex = (handleSegmentIndex + 1) % actualHandleCount
                        handleSegmentSubIndex = (i - actualHandleCount) / actualHandleCount

                        pT = float(handleSegmentSubIndex + 1) / float(handlesPerSegment + 1)
                        pFrom = axisHandlesSorted[handleSegmentIndex][1]
                        pTo = axisHandlesSorted[handleEndSegmendIndex][1]

                        angleFrom = axisHandlesSorted[handleSegmentIndex][2]
                        angleTo = axisHandlesSorted[handleEndSegmendIndex][2]

                        # Wrap around in last segment
                        if handleSegmentIndex + 1 >= actualHandleCount:
                            pTo += maxParam
                        
                        # Interpolate both parameters and angle...
                        lerpP = pFrom + (pTo - pFrom) * pT
                        lerpAngle = angleFrom + (angleTo - angleFrom)  * pT

                        curveParameterPlug.setFloat(lerpP)
                        curveAnglePlug.setDouble(lerpAngle)

                    else:
                        # Default case... just add them over the curve
                        curveParameterPlug.setFloat(self.curveFn.findParamFromLength(self.curveFn.length() * float(i) / float(self.manipCount)))

                fnDisc = OpenMayaUI.MFnDiscManip(self.manipHandleList[i][1])
                fnDisc.connectToAnglePlug(curveAnglePlug)
                discCenterIndex = fnDisc.centerIndex()
                discAxisIndex = fnDisc.axisIndex()

                self.addPlugToManipConversion(discCenterIndex)
                self.addPlugToManipConversion(discAxisIndex)

                self.manipIndexCallbacks[discCenterIndex] = (self.discCenterConversion, i) # Store index value
                self.manipIndexCallbacks[discAxisIndex] = (self.discAxisConversion, i) # Store index value

            self.finishAddingManips()        
            OpenMayaMPx.MPxManipContainer.connectToDependNode(self, node)

        except:    
            sys.stderr.write('Failed trying to connect manipulators. Stack trace: \n')
            sys.stderr.write(traceback.format_exc())

    def discAxisConversion(self, manipTuple):

        fnCurvePoint = OpenMayaUI.MFnPointOnCurveManip(manipTuple[0])        
        param = fnCurvePoint.parameter()

        normal = self.curveFn.normal(param)
        tangent = self.curveFn.tangent(param)

        numData = OpenMaya.MFnNumericData()
        numDataObj = numData.create(OpenMaya.MFnNumericData.k3Double)
        numData.setData3Double(tangent.x, tangent.y, tangent.z)
        manipData = OpenMayaUI.MManipData(numDataObj)
        return manipData

    def discCenterConversion(self, manipTuple):

        fnCurvePoint = OpenMayaUI.MFnPointOnCurveManip(manipTuple[0])
        center = fnCurvePoint.curvePoint()

        numData = OpenMaya.MFnNumericData()
        numDataObj = numData.create(OpenMaya.MFnNumericData.k3Double)
        numData.setData3Double(center.x, center.y, center.z)
        manipData = OpenMayaUI.MManipData(numDataObj)
        return manipData

    def plugToManipConversion(self, manipIndex):

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
    mplugin = OpenMayaMPx.MFnPlugin( mobject, "mmerchante", kPluginVersion )
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

### UTILS
def getSingleSourceObjectFromPlug(plug):

    if plug.isConnected():
        # Get connected input plugs
        connections = OpenMaya.MPlugArray()
        plug.connectedTo(connections, True, False)

        # Find input transform
        if connections.length() == 1:
            return connections[0].node()

    return None

def getFnFromPlug(plug, fnType):
    node = getSingleSourceObjectFromPlug(plug)

    # Get Fn from a DAG path to get the world transformations correctly
    if node is not None:
        path = OpenMaya.MDagPath()
        trFn = OpenMaya.MFnDagNode(node)
        trFn.getPath(path)

        path.extendToShape()

        if path.node().hasFn(fnType):
            return path

    return None

# TODO: cache this data to prevent recalculating when there is no manipulator being updated
def getSortedCurveAxisArray(mObject, curveAxisHandleArray, count):
    axisHandles = []

    expectedHandleCount = OpenMaya.MFnDependencyNode(mObject).findPlug(instanceAlongCurveLocator.curveAxisHandleCountAttr).asInt()

    for i in xrange(min(expectedHandleCount, curveAxisHandleArray.elementCount())):
        curveAxisHandleArray.jumpToArrayElement(i)
        parameterHandle = curveAxisHandleArray.inputValue().child(instanceAlongCurveLocator.curveAxisHandleAttr.parameter)
        angleHandle = curveAxisHandleArray.inputValue().child(instanceAlongCurveLocator.curveAxisHandleAttr.angle)
        axisHandles.append((i, parameterHandle.asDouble(), angleHandle.asDouble()))

    def getKey(item):
        return item[1]

    return sorted(axisHandles, key=getKey)
