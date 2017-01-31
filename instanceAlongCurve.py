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

    # Legacy attributes to support backward compatibility
    legacyInputTransformAttr = OpenMaya.MObject()

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

    # Scale offset
    inputLocalScaleOffsetAttr = OpenMaya.MObject()

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
            self.rampRepeat = OpenMaya.MObject()

    # Simple container class for compound vector attributes
    class RampValueContainer(object):

        def __init__(self, mObject, dataBlock, rampAttr, normalize, instanceCount):            
            self.ramp = OpenMaya.MRampAttribute(OpenMaya.MPlug(mObject, rampAttr.ramp))
            self.rampOffset = dataBlock.inputValue(rampAttr.rampOffset).asFloat()
            self.rampRandomAmplitude = dataBlock.inputValue(rampAttr.rampRandomAmplitude).asFloat()
            self.rampAmplitude = dataBlock.inputValue(rampAttr.rampAmplitude).asFloat()
            self.rampRepeat = dataBlock.inputValue(rampAttr.rampRepeat).asFloat()

            if normalize:
                self.rampAxis = dataBlock.inputValue(rampAttr.rampAxis.compound).asVector().normal()
            else:
                self.rampAxis = dataBlock.inputValue(rampAttr.rampAxis.compound).asVector()

            self.useDynamicAmplitudeValues = False

            amplitudePlug = OpenMaya.MPlug(mObject, rampAttr.rampAmplitude)

            if amplitudePlug.isConnected():

                # Get connected input plugs
                connections = OpenMaya.MPlugArray()
                amplitudePlug.connectedTo(connections, True, False)

                # Find input transform
                if connections.length() == 1:
                    node = connections[0].node()
                    nodeFn = OpenMaya.MFnDependencyNode(node)

                    resultColors = OpenMaya.MFloatVectorArray()
                    resultTransparencies = OpenMaya.MFloatVectorArray()

                    uValues = OpenMaya.MFloatArray(instanceCount, 0.0)
                    vValues = OpenMaya.MFloatArray(instanceCount, 0.0)

                    # Sample a line, for more user flexibility
                    for i in xrange(instanceCount):
                        uValues.set(i / float(instanceCount), i)
                        vValues.set(i / float(instanceCount), i)

                    # For now... then we can just use the plug (TODO)
                    if(node.hasFn(OpenMaya.MFn.kTexture2d)):                        
                        
                        OpenMayaRender.MRenderUtil.sampleShadingNetwork(nodeFn.name() + ".outColor", instanceCount, False, False, OpenMaya.MFloatMatrix(), None, uValues, vValues, None, None, None, None, None, resultColors, resultTransparencies)

                        self.rampAmplitudeValues = []
                        self.useDynamicAmplitudeValues = True

                        for i in xrange(resultColors.length()):
                            self.rampAmplitudeValues.append(resultColors[i].length() / math.sqrt(3))

    # Ramps base offset
    distOffsetAttr = OpenMaya.MObject()

    # Normalized thresholds for curve evaluation
    curveStartAttr = OpenMaya.MObject()
    curveEndAttr = OpenMaya.MObject()

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

                rotatePivot = inputTransformFn.rotatePivot(OpenMaya.MSpace.kTransform )
                scalePivot = inputTransformFn.scalePivot(OpenMaya.MSpace.kTransform )

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

                    # Pivots
                    instanceFn.setRotatePivot(rotatePivot, OpenMaya.MSpace.kTransform , False)
                    instanceFn.setScalePivot(scalePivot, OpenMaya.MSpace.kTransform , False)

                    instanceTranslatePlug = instanceFn.findPlug('translate', False)
                    outputTranslationPlugElement = outputTranslationPlug.elementByLogicalIndex(i)

                    instanceRotationPlug = instanceFn.findPlug('rotate', False)
                    outputRotationPlugElement = outputRotationPlug.elementByLogicalIndex(i)

                    instanceScalePlug = instanceFn.findPlug('scale', False)
                    outputScalePlugElement = outputScalePlug.elementByLogicalIndex(i)

                    # Make instance visible
                    instanceFn.findPlug("visibility", False).setBool(True)

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
        isCorrectAttribute = isCorrectAttribute or (plug.attribute() == instanceAlongCurveLocator.curveStartAttr)
        isCorrectAttribute = isCorrectAttribute or (plug.attribute() == instanceAlongCurveLocator.curveEndAttr)

        isCorrectNode = OpenMaya.MFnDependencyNode(plug.node()).typeName() == kPluginNodeName

        try:
            if isCorrectNode and isCorrectAttribute and attributeSet and incomingDirection:
                self.updateInstanceConnections()
        except:    
            sys.stderr.write('Failed trying to update instances. stack trace: \n')
            sys.stderr.write(traceback.format_exc())

    def getInputTransformPlug(self):

        # Backward compatibility
        inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
        legacyInputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.legacyInputTransformAttr)

        if(legacyInputTransformPlug.isConnected()):
            inputTransformPlug = legacyInputTransformPlug

        return inputTransformPlug

    def getInputTransformFn(self):

        inputTransformPlug = self.getInputTransformPlug()
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

            # Known issue: even if the curve fn is dag path constructed, its length is not worldspace... 
            # If you want perfect distance-based instancing, freeze the transformations of the curve
            curveLength = curveFn.length()

            curveStart = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.curveStartAttr).asFloat() * curveLength
            curveEnd = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.curveEndAttr).asFloat() * curveLength

            effectiveCurveLength = min(max(curveEnd - curveStart, 0.001), curveLength)

            return min(maxInstancesByLengthPlug.asInt(), int(math.ceil(effectiveCurveLength / instanceLengthPlug.asFloat())))

        instanceCountPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instanceCountAttr)
        return instanceCountPlug.asInt()

    def getRandomizedValueUnified(self, randomValue, randomAmplitude, value):
        return (randomValue * 2.0 - 1.0) * randomAmplitude + value

    def getRandomizedValue(self, random, randomAmplitude, value):
        return (random.random() * 2.0 - 1.0) * randomAmplitude + value

    # Calculate expected instances by the instancing mode
    def getIncrementByMode(self, count, effectiveCurveLength):
        instancingModePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instancingModeAttr)
       
        # Distance defined manually
        if instancingModePlug.asInt() == 1:
            instanceLengthPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instanceLengthAttr)            
            return instanceLengthPlug.asFloat()
        
        # Distance driven by count
        return effectiveCurveLength / float(count)

    def updateInstancePositions(self, curveFn, dataBlock, count, distOffset, curveStart, curveEnd, effectiveCurveLength, lengthIncrement, inputTransformPlug, inputTransformFn, axisHandlesSorted):

            # Common data
            translateArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputTranslationAttr.compound)
            curveLength = curveFn.length()
            maxParam = curveFn.findParamFromLength(curveLength)
            curveForm = curveFn.form()

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

            # Local offset is not considered for position
            localRotation = forward.rotateTo(referenceAxis)

            # Manipulator data
            enableManipulators = dataBlock.inputValue(instanceAlongCurveLocator.enableManipulatorsAttr).asBool()

            # Local translation offsets
            localTranslationOffset = dataBlock.inputValue(instanceAlongCurveLocator.inputLocalTranslationOffsetAttr.compound).asVector()
            globalTranslationOffset = dataBlock.inputValue(instanceAlongCurveLocator.inputGlobalTranslationOffsetAttr.compound).asVector()
            
            # Get pivot
            rotatePivot = OpenMaya.MVector()

            if inputTransformPlug.isConnected():
                rotatePivot = OpenMaya.MVector(inputTransformFn.rotatePivot(OpenMaya.MSpace.kTransform ))
                rotatePivot += OpenMaya.MVector(inputTransformFn.rotatePivotTranslation(OpenMaya.MSpace.kTransform ))

            # Deterministic random
            random.seed(count)
            rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.positionRampAttr, False, count)

            inputTransformRotation = OpenMaya.MQuaternion()

            # First, map parameter
            if inputTransformPlug.isConnected():
                inputTransformFn.getRotation(inputTransformRotation, OpenMaya.MSpace.kWorld)

            # Make sure there are enough handles...
            for i in xrange(min(count, translateArrayHandle.elementCount())):

                dist = math.fmod(curveStart + math.fmod(lengthIncrement * i + distOffset, effectiveCurveLength), curveLength)
                param = max( min( curveFn.findParamFromLength( dist ), maxParam ), 0.0)

                # Ramps are not modified by curve start/end, so objects can "slide"
                normalizedDistance = dist / curveFn.length()
                rampValue = self.getRampValueAtNormalizedPosition(rampValues, normalizedDistance)
                
                # Get the actual point on the curve...
                point = OpenMaya.MPoint()
                curveFn.getPointAtParam(param, point)

                tangent = curveFn.tangent(param)
                rot = referenceAxis.rotateTo(tangent)

                # If the axis is parallel, but with inverse direction, rotate it PI over the up vector
                if referenceAxis.isParallel(tangent) and (referenceAxis * tangent < 0):
                    rot = OpenMaya.MQuaternion(math.pi, referenceUp)

                # Transform rotation so that it is aligned with the tangent. This fixes unintentional twisting
                rot = localRotation * rot
                
                # Modify resulting rotation based on mode
                if rotMode == 0:                    # Identity
                    rot = OpenMaya.MQuaternion()
                elif rotMode == 1:                  # Input rotation
                    rot = inputTransformRotation;
                elif rotMode == 3 and i % 2 == 1:   # Chain mode, interesting for position ;)
                    rot *= OpenMaya.MQuaternion(math.pi * .5, tangent)

                # Get the angle from handles, and rotate over tangent axis
                if enableManipulators:
                    angle = self.getRotationForParam(param, axisHandlesSorted, curveForm, maxParam)
                    rot = rot * OpenMaya.MQuaternion(-angle, tangent)

                # The curve basis used for twisting
                basisForward = forward.rotateBy(rot)
                basisUp = up.rotateBy(rot)
                basisRight = right.rotateBy(rot)

                rampAmplitude = self.getRampAmplitudeForInstance(rampValues, i)

                twistNormal = basisRight * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.x
                twistTangent = basisUp * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.y
                twistBitangent = basisForward * self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.z

                twist = (twistNormal + twistTangent + twistBitangent)

                # Twist + global offset, without pivot
                point += twist + globalTranslationOffset - rotatePivot

                # Local offset
                point += basisRight * localTranslationOffset.x + basisUp * localTranslationOffset.y + basisForward * localTranslationOffset.z

                translateArrayHandle.jumpToArrayElement(i)
                translateHandle = translateArrayHandle.outputValue()
                translateHandle.set3Double(point.x, point.y, point.z)

            translateArrayHandle.setAllClean()
            translateArrayHandle.setClean()

    def getRampAmplitudeForInstance(self, rampValues, instanceIndex):

        if rampValues.useDynamicAmplitudeValues:

            if len(rampValues.rampAmplitudeValues) > instanceIndex:
                return rampValues.rampAmplitudeValues[instanceIndex]

        return rampValues.rampAmplitude

    def getRampValueAtNormalizedPosition(self, rampValues, v):

        util = OpenMaya.MScriptUtil()
        util.createFromDouble(0.0)
        valuePtr = util.asFloatPtr()
        
        position = math.fmod((v * rampValues.rampRepeat) + rampValues.rampOffset, 1.0)
        rampValues.ramp.getValueAtPosition(position, valuePtr)

        return util.getFloat(valuePtr)

    def updateInstanceScale(self, curveFn, dataBlock, count, distOffset, curveStart, curveEnd, effectiveCurveLength, lengthIncrement):

            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            maxParam = curveFn.findParamFromLength(curveLength)
            scaleArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputScaleAttr.compound)

            localScaleOffset = dataBlock.inputValue(instanceAlongCurveLocator.inputLocalScaleOffsetAttr.compound).asVector()

            # Deterministic random
            random.seed(count)
            rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.scaleRampAttr, False, count)

            # Make sure there are enough handles...
            for i in xrange(min(count, scaleArrayHandle.elementCount())):

                dist = math.fmod(curveStart + math.fmod(lengthIncrement * i + distOffset, effectiveCurveLength), curveLength)
                param = max( min( curveFn.findParamFromLength( dist ), maxParam ), 0.0)

                # Ramps are not modified by curve start/end, so objects can "slide"
                normalizedDistance = dist / curveFn.length()
                rampValue = self.getRampValueAtNormalizedPosition(rampValues, normalizedDistance)

                unifiedRandom = random.random()
                rampAmplitude = self.getRampAmplitudeForInstance(rampValues, i)

                # Scales are unified... because it makes more sense
                point.x = localScaleOffset.x + self.getRandomizedValueUnified(unifiedRandom, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.x
                point.y = localScaleOffset.y + self.getRandomizedValueUnified(unifiedRandom, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.y
                point.z = localScaleOffset.z + self.getRandomizedValueUnified(unifiedRandom, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.z

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

    def updateInstanceRotations(self, curveFn, dataBlock, count, distOffset, curveStart, curveEnd, effectiveCurveLength, lengthIncrement, inputTransformPlug, inputTransformFn, axisHandlesSorted):

        # Common data
        curveLength = curveFn.length()
        maxParam = curveFn.findParamFromLength(curveLength)
        curveForm = curveFn.form()
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

        # Rotation to align selected (local) forward axis to the reference forward axis (which is aligned with tangent)
        localRotation = localRotationOffset * forward.rotateTo(referenceAxis)

        # Deterministic random
        random.seed(count)
        rampValues = instanceAlongCurveLocator.RampValueContainer(self.thisMObject(), dataBlock, instanceAlongCurveLocator.rotationRampAttr, True, count)

        # Manipulator stuff
        enableManipulators = dataBlock.inputValue(instanceAlongCurveLocator.enableManipulatorsAttr).asBool()

        # Original transform data
        inputTransformRotation = OpenMaya.MQuaternion()

        # First, map parameter
        if inputTransformPlug.isConnected():
            inputTransformFn.getRotation(inputTransformRotation, OpenMaya.MSpace.kWorld)

        for i in xrange(min(count, rotationArrayHandle.elementCount())):
            
            dist = math.fmod(curveStart + math.fmod(lengthIncrement * i + distOffset, effectiveCurveLength), curveLength)
            param = max( min( curveFn.findParamFromLength( dist ), maxParam ), 0.0)

            # Ramps are not modified by curve start/end, so objects can "slide"
            normalizedDistance = dist / curveFn.length()
            rampValue = self.getRampValueAtNormalizedPosition(rampValues, normalizedDistance)

            tangent = curveFn.tangent(param)

            # Reference axis (Z) is now aligned with tangent
            rot = referenceAxis.rotateTo(tangent)

            # If the axis is parallel, but with inverse direction, rotate it PI over the up vector
            if referenceAxis.isParallel(tangent) and (referenceAxis * tangent < 0):
                rot = OpenMaya.MQuaternion(math.pi, referenceUp)

            # Rotate local axis to align with tangent
            rot = localRotation * rot
            
            # The curve basis used for twisting        
            basisForward = forward.rotateBy(rot)
            basisUp = up.rotateBy(rot)
            basisRight = right.rotateBy(rot)

            rampAmplitude = self.getRampAmplitudeForInstance(rampValues, i)

            twistNormal = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.x                
            twistNormal = OpenMaya.MQuaternion(math.radians(twistNormal), basisRight) #X

            twistTangent = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.y
            twistTangent = OpenMaya.MQuaternion(math.radians(twistTangent), basisUp) #Y

            twistBitangent = self.getRandomizedValue(random, rampValues.rampRandomAmplitude, rampValue * rampAmplitude) * rampValues.rampAxis.z
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

            updateTranslation = (plug == instanceAlongCurveLocator.outputTranslationAttr.compound)
            updateRotation = (plug == instanceAlongCurveLocator.outputRotationAttr.compound)
            updateScale = (plug == instanceAlongCurveLocator.outputScaleAttr.compound)

            if not curve.isNull():

                if updateTranslation or updateRotation or updateScale:
                    curveFn = OpenMaya.MFnNurbsCurve(curve)

                    instanceCount = self.getInstanceCountByMode()
                    distOffset = dataBlock.inputValue(instanceAlongCurveLocator.distOffsetAttr).asFloat()
                    curveLength = curveFn.length()

                    # Curve thresholds
                    curveStart = dataBlock.inputValue(instanceAlongCurveLocator.curveStartAttr).asFloat() * curveLength
                    curveEnd = dataBlock.inputValue(instanceAlongCurveLocator.curveEndAttr).asFloat() * curveLength

                    effectiveCurveLength = min(max(curveEnd - curveStart, 0.001), curveLength)
                    lengthIncrement = self.getIncrementByMode(instanceCount, effectiveCurveLength)

                    # Common data
                    inputTransformPlug = self.getInputTransformPlug()
                    inputTransformFn = self.getInputTransformFn()
                    
                    # Force update of transformation 
                    if OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr).isConnected():
                        dataBlock.inputValue(inputTransformPlug).asMatrix()

                    # Manipulator data
                    curveAxisHandleArray = dataBlock.inputArrayValue(instanceAlongCurveLocator.curveAxisHandleAttr.compound)
                    axisHandlesSorted = getSortedCurveAxisArray(self.thisMObject(), curveAxisHandleArray, instanceCount)

                    if updateTranslation:
                        self.updateInstancePositions(curveFn, dataBlock, instanceCount, distOffset, curveStart, curveEnd, effectiveCurveLength, lengthIncrement, inputTransformPlug, inputTransformFn, axisHandlesSorted)

                    if updateRotation:
                        self.updateInstanceRotations(curveFn, dataBlock, instanceCount, distOffset, curveStart, curveEnd, effectiveCurveLength, lengthIncrement, inputTransformPlug, inputTransformFn, axisHandlesSorted)

                    if updateScale:
                        self.updateInstanceScale(curveFn, dataBlock, instanceCount, distOffset, curveStart, curveEnd, effectiveCurveLength, lengthIncrement)

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

        rampAttributes.rampAmplitude = nAttr.create(attributeName + "RampAmplitude", attributeName + "RampAmplitude", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setKeyable( True )
        cls.addAttribute( rampAttributes.rampAmplitude )

        rampAttributes.rampRepeat = nAttr.create(attributeName + "RampRepeat", attributeName + "RampRepeat", OpenMaya.MFnNumericData.kFloat, 1.0)
        nAttr.setKeyable( True )
        cls.addAttribute( rampAttributes.rampRepeat )

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
        matrixAttrFn = OpenMaya.MFnMatrixAttribute()
        msgAttributeFn = OpenMaya.MFnMessageAttribute()
        curveAttributeFn = OpenMaya.MFnTypedAttribute()
        enumFn = OpenMaya.MFnEnumAttribute()

        node.inputTransformAttr = matrixAttrFn.create("inputTransformMatrix", "inputTransformMatrix", OpenMaya.MFnMatrixAttribute.kFloat)
        node.addAttribute( node.inputTransformAttr )

        node.legacyInputTransformAttr = msgAttributeFn.create("inputTransform", "it")
        node.addAttribute( node.legacyInputTransformAttr)

        node.inputShadingGroupAttr = msgAttributeFn.create("inputShadingGroup", "iSG")    
        node.addAttribute( node.inputShadingGroupAttr )

        # Input curve transform
        node.inputCurveAttr = curveAttributeFn.create( 'inputCurve', 'curve', OpenMaya.MFnData.kNurbsCurve)
        node.addAttribute( node.inputCurveAttr )
        
        # Input instance count    
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

        node.addCompoundVector3Attribute(node.inputLocalScaleOffsetAttr, "inputLocalScaleOffset", OpenMaya.MFnUnitAttribute.kDistance, False, True, OpenMaya.MVector(1.0, 1.0, 1.0))

        # Curve parameter offset
        node.distOffsetAttr = nAttr.create("distOffset", "pOffset", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setMin(0.0)
        nAttr.setKeyable( True )
        node.addAttribute( node.distOffsetAttr )

        node.curveStartAttr = nAttr.create("curveStart", "cStart", OpenMaya.MFnNumericData.kFloat, 0.0)
        nAttr.setMin(0.0)
        nAttr.setSoftMax(1.0)
        nAttr.setKeyable( True )
        node.addAttribute( node.curveStartAttr)

        node.curveEndAttr = nAttr.create("curveEnd", "cEnd", OpenMaya.MFnNumericData.kFloat, 1.0)
        nAttr.setMin(0.0)
        nAttr.setSoftMax(1.0)
        nAttr.setKeyable( True )
        node.addAttribute( node.curveEndAttr)

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

        # Default translation ramp axis is UP
        node.addRampAttributes(node.positionRampAttr, "position", OpenMaya.MFnUnitAttribute.kDistance, OpenMaya.MVector(0.0, 1.0, 0.0))

        # Default rotation ramp axis is TANGENT
        node.addRampAttributes(node.rotationRampAttr, "rotation", OpenMaya.MFnUnitAttribute.kDistance, OpenMaya.MVector(0.0, 0.0, 1.0))

        # Default scale axis is uniform
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
            node.attributeAffects( rampAttributes.rampRepeat, affectedAttr)

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

        node.attributeAffects( node.curveStartAttr, node.outputTranslationAttr.compound )
        node.attributeAffects( node.curveEndAttr, node.outputTranslationAttr.compound )

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

        node.attributeAffects( node.curveStartAttr, node.outputRotationAttr.compound )
        node.attributeAffects( node.curveEndAttr, node.outputRotationAttr.compound )

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

        node.attributeAffects( node.curveStartAttr, node.outputScaleAttr.compound )
        node.attributeAffects( node.curveEndAttr, node.outputScaleAttr.compound )

        node.attributeAffects(node.inputLocalScaleOffsetAttr.compound, node.outputScaleAttr.compound )

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

            # Suppress all attributes, so that no extra controls are shown
            for attr in pm.listAttr(nodeName):
                self.suppress(attr)

            self.callCustom(lambda: self.showTitle(), lambda: None)

            self.beginScrollLayout()

            self.beginLayout("General", collapse=0)

            # Base controls
            annotation = "Defines if the amount of instances is defined manually or by a predefined distance."
            self.addControl("instancingMode", label="Instancing Mode", changeCommand=self.onInstanceModeChanged, annotation=annotation)

            annotation = "The amount of instances to distribute. These are distributed uniformly."
            self.addControl("instanceCount", label="Count", changeCommand=self.onInstanceModeChanged, annotation=annotation)

            annotation = "If the locator mode is on Distance, this length will define the spacing between each instance. <br> <br> Note that if the curve length is greater than an integer amount of distances, some space will be left unoccupied."
            self.addControl("instanceLength", label="Distance", changeCommand=self.onInstanceModeChanged, annotation=annotation)

            annotation = "A safe guard to prevent having too many instances."
            self.addControl("maxInstancesByLength", label="Max Instances", changeCommand=self.onInstanceModeChanged, annotation=annotation)

            self.addSeparator()

            annotation = "An offset for the evaluation of the curve position/rotation. This also modifies the ramp evaluation. "
            self.addControl("distOffset", label="Curve Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "distOffset"), annotation=annotation)

            annotation = "A cutoff value for the curve start point. This is normalized, so it should be in [0,1), but can have greater values for looping"
            self.addControl("curveStart", label="Curve Start", changeCommand=lambda nodeName: self.updateDimming(nodeName, "curveStart"), annotation=annotation)

            annotation = "A cutoff value for the curve end point. This is normalized, so it should be in (0,1], but can have greater values for looping"
            self.addControl("curveEnd", label="Curve End", changeCommand=lambda nodeName: self.updateDimming(nodeName, "curveEnd"), annotation=annotation)

            self.addSeparator()

            # Orientation controls
            annotation = "Identity: objects have no rotation. <br> <br> Copy From Source: Each object will copy the rotation transformation from the original. <br> <br> Use Curve: Objects will be aligned by the curve tangent with respect to the selected axis. <br> <br> Chain: Same as Use Curve, but with an additional 90 degree twist for odd instances."
            self.addControl("orientationMode", label="Orientation Mode", changeCommand=lambda nodeName: self.updateOrientationChange(nodeName), annotation=annotation)

            annotation = "Each instance will be rotated so that this axis is parallel to the curve tangent."
            self.addControl("inputLocalOrientationAxis", label="Local Axis" , changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputLocalOrientationAxis"), annotation=annotation)

            self.addSeparator()

            # Manipulator controls
            annotation = "When enabled, the rotations can be manually defined."
            self.addControl("enableManipulators", label="Enable manipulators", changeCommand=lambda nodeName: self.updateManipCountDimming(nodeName), annotation=annotation)

            annotation = "This number will define the number of handles to manipulate the curve orientation. For changes to take effect, you must click the Edit Manipulators button. <br> <br> When incrementing the number, new handles will be created in between existing ones, interpolating their values."
            self.addControl("curveAxisHandleCount", label="Manipulator count", changeCommand=lambda nodeName: self.updateManipCountDimming(nodeName), annotation=annotation)
            self.callCustom(lambda attr: self.buttonNew(nodeName), self.buttonUpdate, "curveAxisHandleCount")

            self.addSeparator()

            # Instance look controls
            annotation = "By default, objects display type is on Reference, so they cannot be selected. To change this, select Normal."
            self.addControl("instanceDisplayType", label="Instance Display Type", changeCommand=lambda nodeName: self.updateDimming(nodeName, "instanceDisplayType"), annotation=annotation)

            annotation = "When true, objects will be shown as bounding boxes only."
            self.addControl("instanceBoundingBox", label="Use bounding box", changeCommand=lambda nodeName: self.updateDimming(nodeName, "instanceBoundingBox"), annotation=annotation)
            
            self.addSeparator()

            self.endLayout()
            
            def showRampControls(rampName):

                self.beginLayout(rampName.capitalize() + " Control", collapse=True)
                mel.eval('AEaddRampControl("' + nodeName + "." + rampName + 'Ramp"); ')

                annotation = "An offset when evaluating the ramp. This is similar to the curve offset, but works only for the ramp."
                self.addControl(rampName + "RampOffset", label= rampName.capitalize() + " Ramp Offset", annotation=annotation)

                annotation = "A multiplier to evaluate multiple times the same ramp over the curve"
                self.addControl(rampName + "RampRepeat", label= rampName.capitalize() + " Ramp Repeat", annotation=annotation)

                annotation = "Ramp values are multiplied by this amplitude."
                self.addControl(rampName + "RampAmplitude", label= rampName.capitalize() + " Ramp Amplitude", annotation=annotation)

                annotation = "A random value for the ramp amplitude. The result is <br><br> amplitude + (random() * 2.0 - 1.0) * <b>randomAmplitude</b>"
                self.addControl(rampName + "RampRandomAmplitude", label= rampName.capitalize() + " Ramp Random", annotation=annotation)

                annotation = "The axis over which the ramp is evaluated. The result depends on the type of ramp. <br> <br> The (X,Y,Z) values are over the local space of the transformed object (right/bitangent, up/normal, forward/tangent)."
                self.addControl(rampName + "RampAxis", label= rampName.capitalize() + " Ramp Axis", annotation=annotation)

                self.endLayout()

            self.beginLayout("Offsets", collapse=True)

            annotation = "A translation offset over the curve local space."
            self.addControl("inputLocalTranslationOffset", label="Local Translation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputLocalTranslationOffset"), annotation=annotation)

            annotation = "A translation offset in worldspace XYZ."
            self.addControl("inputGlobalTranslationOffset", label="Global Translation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputGlobalTranslationOffset"), annotation=annotation)

            self.addSeparator()

            annotation = "A rotation offset over the curve local space. This offset is initialized to the original object rotation. "
            self.addControl("inputLocalRotationOffset", label="Local Rotation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputLocalRotationOffset"), annotation=annotation)

            annotation = "A worldspace rotation offset."
            self.addControl("inputGlobalRotationOffset", label="Global Rotation Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputGlobalRotationOffset"), annotation=annotation)

            self.addSeparator()

            annotation = "A scale offset over the object local space. This offset is initialized to the original object scale."
            self.addControl("inputLocalScaleOffset", label="Local Scale Offset", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputLocalScaleOffset"), annotation=annotation)
            
            self.endLayout()

            showRampControls("position")
            showRampControls("rotation")
            showRampControls("scale")

            self.beginLayout("Extra", collapse=True)

            # Additional info
            annotation = "The input object transform. DO NOT REMOVE THIS CONNECTION, or the node will stop working correctly."
            self.addControl("inputTransformMatrix", label="Input object", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputTransformMatrix"), annotation=annotation)

            annotation = "The shading group for the instances. When instantiating, they will be assigned this SG."
            self.addControl("inputShadingGroup", label="Shading Group", changeCommand=lambda nodeName: self.updateDimming(nodeName, "inputShadingGroup"), annotation=annotation)

            self.endLayout()

            self.endScrollLayout()

    def showTitle(self):
        pm.text("Instance Along Curve v" + kPluginVersion, font="boldLabelFont")

    def buttonNew(self, nodeName):

        # pm.separator( height=5, style='none')
        pm.rowLayout(numberOfColumns=3, adjustableColumn=1, columnWidth3=(80, 100, 100))

        self.updateManipButton = pm.button( label='Edit Manipulators...', command=lambda *args: self.onEditManipulators(nodeName))
        self.updateManipButton.setAnnotation("When pressed, the manipulators will be selected. If the manipulator count changed, it will be updated.")

        self.resetPositionsButton = pm.button( label='Reset Positions', command=lambda *args: self.onResetManipPositions(nodeName))
        self.resetPositionsButton.setAnnotation("When pressed, the manipulators will be uniformly distributed over the curve.")

        self.resetAnglesButton = pm.button( label='Reset Angles', command=lambda *args: self.onResetManipAngles(nodeName))
        self.resetAnglesButton.setAnnotation("When pressed, all the manipulator angles will be reset to 0.")
    
    def buttonUpdate(self, attr):

        nodeName = pm.PyNode(attr).nodeName()
        self.updateManipButton.setCommand(lambda *args: self.onEditManipulators(nodeName))
        self.resetPositionsButton.setCommand(lambda *args: self.onResetManipPositions(nodeName))
        self.resetAnglesButton.setCommand(lambda *args: self.onResetManipAngles(nodeName))
    
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

        enableManips = pm.PyNode(nodeName).enableManipulators.get()

        self.updateManipButton.setEnable(enableManips)
        self.resetAnglesButton.setEnable(enableManips)
        self.resetPositionsButton.setEnable(enableManips)        
        self.updateDimming(nodeName, "curveAxisHandleCount", enableManips)

    def updateDimming(self, nodeName, attr, additionalCondition = True):

        if pm.PyNode(nodeName).type() == kPluginNodeName:

            node = pm.PyNode(nodeName)
            instanced = node.isInstanced()
            hasInputTransform = node.inputTransform.isConnected() or node.inputTransformMatrix.isConnected()
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
                    transformMessagePlug = transformFn.findPlug("worldMatrix", True)
                    transformMessagePlug = transformMessagePlug.elementByLogicalIndex(0)

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
                    mdagModifier = OpenMaya.MDagModifier()
                    self.mUndo.append(mdagModifier)               
                    mdagModifier.connect(curvePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputCurveAttr))
                    mdagModifier.connect(transformMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputTransformAttr))

                    if shadingGroupFn is not None:
                        shadingGroupMessagePlug = shadingGroupFn.findPlug("message", True)
                        mdagModifier.connect(shadingGroupMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputShadingGroupAttr))

                    mdagModifier.doIt()

                    # (pymel) create a locator and make it the parent
                    locator = pm.createNode('locator', ss=True, p=newNodeTransformName)

                    # Show AE
                    mel.eval("openAEWindow")

                    instanceCountPlug = newNodeFn.findPlug("instanceCount", False)
                    instanceCountPlug.setInt(10)

                    # Rotation offset initialized to original rotation
                    rotX = transformFn.findPlug("rotateX", False).asMAngle().asDegrees()
                    rotY = transformFn.findPlug("rotateY", False).asMAngle().asDegrees()
                    rotZ = transformFn.findPlug("rotateZ", False).asMAngle().asDegrees()

                    plugOffsetX = newNodeFn.findPlug("inputLocalRotationOffsetX", False)
                    plugOffsetY = newNodeFn.findPlug("inputLocalRotationOffsetY", False)
                    plugOffsetZ = newNodeFn.findPlug("inputLocalRotationOffsetZ", False)

                    plugOffsetX.setDouble(rotX)
                    plugOffsetY.setDouble(rotY)
                    plugOffsetZ.setDouble(rotZ)

                    # Scale offset initialized to original scale
                    scaleX = transformFn.findPlug("scaleX", False).asFloat()
                    scaleY = transformFn.findPlug("scaleY", False).asFloat()
                    scaleZ = transformFn.findPlug("scaleZ", False).asFloat()

                    plugOffsetX = newNodeFn.findPlug("inputLocalScaleOffsetX", False)
                    plugOffsetY = newNodeFn.findPlug("inputLocalScaleOffsetY", False)
                    plugOffsetZ = newNodeFn.findPlug("inputLocalScaleOffsetZ", False)

                    plugOffsetX.setDouble(scaleX)
                    plugOffsetY.setDouble(scaleY)
                    plugOffsetZ.setDouble(scaleZ)
                    
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

        tangent = self.curveFn.tangent(param, OpenMaya.MSpace.kWorld)

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
        if (OpenMaya.MGlobal.mayaState() != OpenMaya.MGlobal.kBatch) and (OpenMaya.MGlobal.mayaState() != OpenMaya.MGlobal.kLibraryApp):
            
            # Register command
            mplugin.registerCommand( kPluginCmdName, instanceAlongCurveCommand.cmdCreator )

            mplugin.addMenuItem("Instance Along Curve", "MayaWindow|mainEditMenu", kPluginCmdName, "")

            # Register AE template
            pm.callbacks(addCallback=loadAETemplateCallback, hook='AETemplateCustomContent', owner=kPluginNodeName)

            # Register IAC manip node
            mplugin.registerNode( kPluginManipNodeName, kPluginNodeManipId, instanceAlongCurveLocatorManip.nodeCreator, instanceAlongCurveLocatorManip.nodeInitializer, OpenMayaMPx.MPxNode.kManipContainer )

        # Register IAC node
        mplugin.registerNode( kPluginNodeName, kPluginNodeId, instanceAlongCurveLocator.nodeCreator,
                              instanceAlongCurveLocator.nodeInitializer, OpenMayaMPx.MPxNode.kLocatorNode, kPluginNodeClassify )

    except:
        sys.stderr.write('Failed to register plugin instanceAlongCurve. stack trace: \n')
        sys.stderr.write(traceback.format_exc())
        raise
    
def uninitializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        mplugin.deregisterNode( kPluginNodeId )

        if (OpenMaya.MGlobal.mayaState() != OpenMaya.MGlobal.kBatch) and (OpenMaya.MGlobal.mayaState() != OpenMaya.MGlobal.kLibraryApp):
            mplugin.deregisterCommand( kPluginCmdName )
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

def printVector(v, s=None):
    print s + ":" + str(v.x) + ", " + str(v.y) + ", " + str(v.z)
