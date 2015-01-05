import sys
import traceback
import pymel.core as pm
import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMaya as OpenMaya
import maya.OpenMayaRender as OpenMayaRender

kPluginCmdName = "instanceAlongCurve"
kPluginNodeName = 'instanceAlongCurveLocator'
kPluginNodeClassify = 'utility/general'
kPluginNodeId = OpenMaya.MTypeId( 0x55555 ) 

glRenderer = OpenMayaRender.MHardwareRenderer.theRenderer()
glFT = glRenderer.glFunctionTable()

# Ideas:
#   - orientation constraints: set a fixed axis?
#   - twisting
#   - scale modes
#   - modulate attributes (pos, rot, scale) along curve's parameter space through user curves

class instanceAlongCurveLocator(OpenMayaMPx.MPxLocatorNode):

    # Input attr
    inputCurveAttr = OpenMaya.MObject()
    inputTransformAttr = OpenMaya.MObject()
    inputShadingGroupAttr = OpenMaya.MObject()

    instanceCountAttr = OpenMaya.MObject()
    instancingModeAttr = OpenMaya.MObject()
    instanceLengthAttr = OpenMaya.MObject()
    maxInstancesByLengthAttr = OpenMaya.MObject()

    knownInstancesAttr = OpenMaya.MObject()
    displayTypeAttr = OpenMaya.MObject()
    bboxAttr = OpenMaya.MObject()

    orientationModeAttr = OpenMaya.MObject()

    # Output sentinel attr for display overrides
    sentinelAttr = OpenMaya.MObject()

    # Output sentinel attr for refreshing positioning/orientation
    sentinelPositioningAttr = OpenMaya.MObject()

    def __init__(self):
        self.triggerUpdate = False
        self.curveTransformCallback = None
        self.curveCallback = None
        self.inputTransformCallback = None
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


    def updateDrawingOverrides(self):
        knownInstancesPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.knownInstancesAttr)
        drawMode = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.displayTypeAttr).asInt()
        useBBox = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.bboxAttr).asBool()

        connections = OpenMaya.MPlugArray()

        for i in xrange(knownInstancesPlug.numConnectedElements()):

            knownPlugElement = knownInstancesPlug.elementByPhysicalIndex(i)
            knownPlugElement.connectedTo(connections, True, False)
            
            for c in xrange(0, connections.length()):
                instanceFn = OpenMaya.MFnTransform(connections[c].node())
                self.setDrawingOverride(instanceFn, drawMode, useBBox)

    def setDrawingOverride(self, nodeFn, drawMode, useBBox):
        overrideEnabledPlug = nodeFn.findPlug("overrideEnabled", False)
        overrideEnabledPlug.setBool(True)

        displayPlug = nodeFn.findPlug("overrideDisplayType", False)
        displayPlug.setInt(drawMode)

        lodPlug = nodeFn.findPlug("overrideLevelOfDetail", False)
        lodPlug.setInt(useBBox)


    # Find original SG to reassign it to instance
    def getSG(self):

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

        if transform is not None and transform.hasFn(OpenMaya.MFn.kTransform):

                # Get Fn from a DAG path to get the world transformations correctly
                path = OpenMaya.MDagPath()
                trFn = OpenMaya.MFnDagNode(transform)
                trFn.getPath(path)

                return OpenMaya.MFnTransform(path)

        return None

    def getCurveFn(self):

        inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)
        curve = self.getSingleSourceObjectFromPlug(inputCurvePlug)

        if curve is not None:
            # Get Fn from a DAG path to get the world transformations correctly
            path = OpenMaya.MDagPath()
            trFn = OpenMaya.MFnDagNode(curve)
            trFn.getPath(path)

            path.extendToShape()

            if path.node().hasFn(OpenMaya.MFn.kNurbsCurve):
                return OpenMaya.MFnNurbsCurve(path)

        return None

    def draw(self, view, path, style, status):

        try:
            self.forceCompute()
            self.updateInstanceConnections(path)

            # Update is done once in the draw method to prevent being flooded with modifications from the curve callback
            if self.triggerUpdate:
                self.updateInstancePositions()
        except:
            sys.stderr.write('Failed trying to update locator. stack trace: \n')
            sys.stderr.write(traceback.format_exc())

        self.triggerUpdate = False

        # Draw simple locator lines
        view.beginGL()
 
        glFT.glBegin(OpenMayaRender.MGL_LINES)
        glFT.glVertex3f(0.0, -0.5, 0.0)
        glFT.glVertex3f(0.0, 0.5, 0.0)
        
        glFT.glVertex3f(0.5, 0.0, 0.0)
        glFT.glVertex3f(-0.5, 0.0, 0.0)

        glFT.glVertex3f(0.0, 0.0, 0.5)
        glFT.glVertex3f(0.0, 0.0, -0.5)      
        glFT.glEnd()
 
        view.endGL()

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
        # If you want to instance this locator, set everything 
        if OpenMaya.MFnDagNode(self.thisMObject()).isInstanced():
            return OpenMaya.kUnknownParameter

        expectedInstanceCount = self.getInstanceCountByMode()
        knownInstancesPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.knownInstancesAttr)

        # Only instance if we are missing elements
        if knownInstancesPlug.numConnectedElements() < expectedInstanceCount:

            inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)

            # Get connected input transform plugs 
            inputTransformConnectedPlugs = OpenMaya.MPlugArray()
            inputTransformPlug.connectedTo(inputTransformConnectedPlugs, True, False)

            # Find input transform
            if inputTransformConnectedPlugs.length() == 1:
                transform = inputTransformConnectedPlugs[0].node()
                transformFn = OpenMaya.MFnTransform(transform)

                drawMode = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.displayTypeAttr).asInt()
                useBBox = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.bboxAttr).asBool()
                self.triggerUpdate = True

                # Get shading group first
                dagPath = OpenMaya.MDagPath()
                transformFn.getPath(dagPath)
                shadingGroupFn = self.getSG()

                mdgModifier = OpenMaya.MDGModifier()

                instanceCount = expectedInstanceCount - knownInstancesPlug.numConnectedElements()
                availableIndices = self.getAvailableLogicalIndices(knownInstancesPlug, instanceCount)

                # Because this is not instanced, it will work
                nodeFn = OpenMaya.MFnDagNode(path.transform())

                # Instance as many times as necessary
                for i in availableIndices:
                    
                    # Instance transform and reassign SG
                    # InstanceLeaf must be set to False to prevent crashes :)
                    trInstance = transformFn.duplicate(True, False)

                    # Parent new instance
                    nodeFn.addChild(trInstance)

                    if shadingGroupFn is not None:
                        shadingGroupFn.addMember(trInstance)

                    instanceFn = OpenMaya.MFnTransform(trInstance)
                    self.setDrawingOverride(instanceFn, drawMode, useBBox)

                    instObjGroupsAttr = instanceFn.attribute('message')
                    instPlugArray = OpenMaya.MPlug(trInstance, instObjGroupsAttr)
                    
                    knownInstancesPlugElement = knownInstancesPlug.elementByLogicalIndex(i)
                    mdgModifier.connect(instPlugArray, knownInstancesPlugElement)

                mdgModifier.doIt()

        # Remove instances if necessary
        elif knownInstancesPlug.numConnectedElements() > expectedInstanceCount:
            self.triggerUpdate = True

            mdgModifier = OpenMaya.MDGModifier()
            connections = OpenMaya.MPlugArray()
            
            numConnectedElements = knownInstancesPlug.numConnectedElements()
            toRemove = knownInstancesPlug.numConnectedElements() - expectedInstanceCount

            for i in xrange(toRemove):

                knownPlugElement = knownInstancesPlug.connectionByPhysicalIndex(numConnectedElements - 1 - i)
                knownPlugElement.connectedTo(connections, True, False)
                
                for c in xrange(connections.length()):
                    node = connections[c].node()
                    mdgModifier.disconnect(connections[c], knownPlugElement)
                    mdgModifier.deleteNode(node)

            mdgModifier.doIt()

        return OpenMaya.kUnknownParameter

    def updateInstancePositions(self):

        knownInstancesPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.knownInstancesAttr)
        inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)
        fnCurve = self.getCurveFn()

        if fnCurve is not None:

            rotMode = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.orientationModeAttr).asInt()

            inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
            inputTransformRotation = OpenMaya.MQuaternion()

            if inputTransformPlug.isConnected():
                self.getInputTransformFn().getRotation(inputTransformRotation, OpenMaya.MSpace.kWorld)

            curveLength = fnCurve.length()

            numConnectedElements = knownInstancesPlug.numConnectedElements()
            point = OpenMaya.MPoint()
            connections = OpenMaya.MPlugArray()

            # TODO: let the user decide forward axis?
            startOrientation = OpenMaya.MVector(0.0, 0.0, 1.0)
            curvePointIndex = 0

            for i in xrange(numConnectedElements):

                param = fnCurve.findParamFromLength(curveLength * (float(curvePointIndex) / numConnectedElements))
                fnCurve.getPointAtParam(param, point, OpenMaya.MSpace.kWorld)

                rot = OpenMaya.MQuaternion()

                if rotMode == 1:
                    rot = inputTransformRotation;
                elif rotMode == 2:
                    normal = fnCurve.normal(param, OpenMaya.MSpace.kWorld)
                    rot = startOrientation.rotateTo(normal)
                elif rotMode == 3:
                    tangent = fnCurve.tangent(param, OpenMaya.MSpace.kWorld)
                    rot = startOrientation.rotateTo(tangent)

                curvePointIndex += 1

                knownPlugElement = knownInstancesPlug.elementByPhysicalIndex(i)
                knownPlugElement.connectedTo(connections, True, False)

                instanceDagPath = OpenMaya.MDagPath()
                
                for c in xrange(0, connections.length()):
                    # Is there a nicer way to do this? dagPath is needed to use kWorld
                    instanceFn = OpenMaya.MFnTransform(connections[c].node())
                    instanceFn.getPath(instanceDagPath)
                    instanceFn = OpenMaya.MFnTransform(instanceDagPath)

                    instanceFn.setTranslation(OpenMaya.MVector(point), OpenMaya.MSpace.kWorld)
                    instanceFn.setRotation(rot, OpenMaya.MSpace.kWorld)

    # Remember to remove callbacks on disconnection
    def connectionBroken(self, plug, otherPlug, asSrc):
        try:
            if plug.attribute() == instanceAlongCurveLocator.inputCurveAttr:

                if self.curveTransformCallback is not None:
                    OpenMaya.MMessage.removeCallback(self.curveTransformCallback)

                if self.curveCallback is not None:
                    OpenMaya.MMessage.removeCallback(self.curveCallback)

            if plug.attribute() == instanceAlongCurveLocator.inputTransformAttr and self.inputTransformCallback is not None:
                OpenMaya.MMessage.removeCallback(self.inputTransformCallback)
        except:
            sys.stderr.write('Failed to disconnect plug ')

        return OpenMaya.kUnknownParameter

    # Get notified when curve shape and transform is modified
    def connectionMade(self, plug, otherPlug, asSrc):
        try:
            if plug.attribute() == instanceAlongCurveLocator.inputCurveAttr:

                dagPath = OpenMaya.MDagPath()

                trDagNode = OpenMaya.MFnDagNode(otherPlug.node())
                trDagNode.getPath(dagPath)

                dagPath.extendToShape()

                # Get callbacks for shape and transform modifications
                self.curveTransformCallback = OpenMaya.MNodeMessage.addNodeDirtyPlugCallback(otherPlug.node(), updatePositioningCallback, self)
                self.curveCallback = OpenMaya.MNodeMessage.addNodeDirtyPlugCallback(dagPath.node(), updatePositioningCallback, self)

                # Update instantly
                self.triggerUpdate = True

            if plug.attribute() == instanceAlongCurveLocator.inputTransformAttr:
                self.inputTransformCallback = OpenMaya.MNodeMessage.addNodeDirtyPlugCallback(otherPlug.node(), updatePositioningCallback, self)

                # Update instantly
                self.triggerUpdate = True
        except:
            sys.stderr.write( 'Failed to connect plug')
        
        return OpenMaya.kUnknownParameter

    # Compute method just for updating current instances display attributes
    def compute(self, plug, dataBlock):

        try:
            if plug == instanceAlongCurveLocator.sentinelAttr:
                self.updateDrawingOverrides()
                dataBlock.setClean(instanceAlongCurveLocator.sentinelAttr)

            if plug == instanceAlongCurveLocator.sentinelPositioningAttr:
                self.updateInstancePositions()
                dataBlock.setClean(instanceAlongCurveLocator.sentinelPositioningAttr)            
        except:
            sys.stderr.write('Failed trying to compute locator. stack trace: \n')
            sys.stderr.write(traceback.format_exc())

        return OpenMaya.kUnknownParameter

    # Query the sentinels' value to force an evaluation
    def forceCompute(self):
        OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.sentinelAttr).asInt()
        OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.sentinelPositioningAttr).asInt()

    @staticmethod
    def nodeCreator():
        return OpenMayaMPx.asMPxPtr( instanceAlongCurveLocator() )

    @staticmethod
    def nodeInitializer():

        nAttr = OpenMaya.MFnNumericAttribute()
        msgAttributeFn = OpenMaya.MFnMessageAttribute()
        curveAttributeFn = OpenMaya.MFnTypedAttribute()
        enumFn = OpenMaya.MFnEnumAttribute()

        instanceAlongCurveLocator.inputTransformAttr = msgAttributeFn.create("inputTransform", "it")
        msgAttributeFn.setWritable( True )
        msgAttributeFn.setStorable( True )
        msgAttributeFn.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.inputTransformAttr )

        instanceAlongCurveLocator.inputShadingGroupAttr = msgAttributeFn.create("inputShadingGroup", "iSG")
        msgAttributeFn.setWritable( True )
        msgAttributeFn.setStorable( True )
        msgAttributeFn.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.inputShadingGroupAttr )

        instanceAlongCurveLocator.knownInstancesAttr = msgAttributeFn.create("knownInstances", "ki")
        msgAttributeFn.setWritable( True )
        msgAttributeFn.setStorable( True )    
        msgAttributeFn.setHidden( True )  
        msgAttributeFn.setArray( True )  
        msgAttributeFn.setDisconnectBehavior(OpenMaya.MFnAttribute.kDelete) # Very important :)
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.knownInstancesAttr )
        
        ## Input instance count    
        instanceAlongCurveLocator.instanceCountAttr = nAttr.create("instanceCount", "iic", OpenMaya.MFnNumericData.kInt, 5)
        nAttr.setMin(1)
        nAttr.setSoftMax(100)
        nAttr.setWritable( True )
        nAttr.setStorable( True )
        nAttr.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.instanceCountAttr)

        ## Max instances when defined by instance length
        instanceAlongCurveLocator.maxInstancesByLengthAttr = nAttr.create("maxInstancesByLength", "mibl", OpenMaya.MFnNumericData.kInt, 50)
        nAttr.setMin(0)
        nAttr.setSoftMax(200)
        nAttr.setWritable( True )
        nAttr.setStorable( True )
        nAttr.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.maxInstancesByLengthAttr)

        # Length between instances
        instanceAlongCurveLocator.instanceLengthAttr = nAttr.create("instanceLength", "ilength", OpenMaya.MFnNumericData.kFloat, 1.0)
        nAttr.setMin(0.01)
        nAttr.setSoftMax(1.0)
        nAttr.setWritable( True )
        nAttr.setStorable( True )
        nAttr.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.instanceLengthAttr)
        
        # Input curve transform
        instanceAlongCurveLocator.inputCurveAttr = msgAttributeFn.create( 'inputCurve', 'curve')
        msgAttributeFn.setWritable( True )
        msgAttributeFn.setStorable( True ) 
        msgAttributeFn.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.inputCurveAttr )

        # Display override options
        instanceAlongCurveLocator.displayTypeAttr = enumFn.create('instanceDisplayType', 'idt')
        enumFn.addField( "Normal", 0 );
        enumFn.addField( "Template", 1 );
        enumFn.addField( "Reference", 2 );
        enumFn.setDefault("Reference")
        enumFn.setWritable( True )
        enumFn.setStorable( True )
        enumFn.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.displayTypeAttr )

        # Enum for selection of instancing mode
        instanceAlongCurveLocator.instancingModeAttr = enumFn.create('instancingMode', 'instancingMode')
        enumFn.addField( "Count", 0 );
        enumFn.addField( "Distance", 1 );
        enumFn.setWritable( True )
        enumFn.setStorable( True )
        enumFn.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.instancingModeAttr )

         # Enum for selection of orientation mode
        instanceAlongCurveLocator.orientationModeAttr = enumFn.create('orientationMode', 'rotMode')
        enumFn.addField( "Identity", 0 );
        enumFn.addField( "Copy from Source", 1 );
        enumFn.addField( "Normal", 2 );
        enumFn.addField( "Tangent", 3 );
        enumFn.setDefault("Tangent")
        enumFn.setWritable( True )
        enumFn.setStorable( True )
        enumFn.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.orientationModeAttr )

        instanceAlongCurveLocator.bboxAttr = nAttr.create('instanceBoundingBox', 'ibb', OpenMaya.MFnNumericData.kBoolean, False)
        nAttr.setWritable( True )
        nAttr.setStorable( True )
        nAttr.setHidden( False )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.bboxAttr )

        ## Output attributes

        # Sentinel to update display overrides
        instanceAlongCurveLocator.sentinelAttr = nAttr.create('sentinel', 's', OpenMaya.MFnNumericData.kInt, 0)
        nAttr.setWritable( False )
        nAttr.setStorable( False )
        nAttr.setReadable( True )
        nAttr.setHidden( True )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.sentinelAttr )

        # Sentinel to update positions/orientations
        instanceAlongCurveLocator.sentinelPositioningAttr = nAttr.create('sentinelPos', 'sPos', OpenMaya.MFnNumericData.kInt, 0)
        nAttr.setWritable( False )
        nAttr.setStorable( False )
        nAttr.setReadable( True )
        nAttr.setHidden( True )
        instanceAlongCurveLocator.addAttribute( instanceAlongCurveLocator.sentinelPositioningAttr )

        # Attribute relationships
        instanceAlongCurveLocator.attributeAffects( instanceAlongCurveLocator.displayTypeAttr, instanceAlongCurveLocator.sentinelAttr )
        instanceAlongCurveLocator.attributeAffects( instanceAlongCurveLocator.bboxAttr, instanceAlongCurveLocator.sentinelAttr )

        instanceAlongCurveLocator.attributeAffects( instanceAlongCurveLocator.orientationModeAttr, instanceAlongCurveLocator.sentinelPositioningAttr )

def updatePositioningCallback(node, plug, self):
    self.triggerUpdate = True

def initializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        # Register command
        # TODO: addmenuItem
        mplugin.registerCommand( kPluginCmdName, instanceAlongCurveCommand.cmdCreator )

        mplugin.addMenuItem("Instance Along Curve", "MayaWindow|mainEditMenu", kPluginCmdName, "")

        # Register AE template
        pm.callbacks(addCallback=loadAETemplateCallback, hook='AETemplateCustomContent', owner=kPluginNodeName)

        # Register node
        mplugin.registerNode( kPluginNodeName, kPluginNodeId, instanceAlongCurveLocator.nodeCreator,
                              instanceAlongCurveLocator.nodeInitializer, OpenMayaMPx.MPxNode.kLocatorNode, kPluginNodeClassify )
    except:
        sys.stderr.write( 'Failed to register plugin instanceAlongCurve')
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
            self.addControl("instanceCount", label="Count")
            self.addControl("instanceLength", label="Distance")
            self.addControl("maxInstancesByLength", label="Max Instances")
            
            self.addSeparator()

            self.addControl("orientationMode", label="Orientation Mode")

            self.addSeparator()
            
            self.addControl("instanceDisplayType", label="Instance Display Type")
            self.addControl("instanceBoundingBox", label="Use bounding box")
            
            self.addSeparator()
            
            self.addControl("inputCurve", label="Input curve")
            self.addControl("inputTransform", label="Input object")
            self.addControl("inputShadingGroup", label="Shading Group")
            self.addExtraControls()

            self.endLayout()
            self.endScrollLayout()

    def onInstanceModeChanged(self, nodeName):
        if pm.PyNode(nodeName).type() == kPluginNodeName:
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


    def findShadingGroup(self, dagPath):
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
                curveTransformFn = OpenMaya.MFnDagNode(curveDagPath.transform())
                curveTransformPlug = curveTransformFn.findPlug("message", True)

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

                OpenMaya.MGlobal.clearSelectionList()
                msel = OpenMaya.MSelectionList()
                msel.add(nodeShapeDagPath)
                OpenMaya.MGlobal.setActiveSelectionList(msel)

                # Connect :D
                mdgModifier = OpenMaya.MDGModifier()
                self.mUndo.append(mdgModifier)               
                mdgModifier.connect(curveTransformPlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputCurveAttr))
                mdgModifier.connect(transformMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputTransformAttr))

                if shadingGroupFn is not None:
                    shadingGroupMessagePlug = shadingGroupFn.findPlug("message", True)
                    mdgModifier.connect(shadingGroupMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputShadingGroupAttr))

                mdgModifier.doIt()
                
            else:
                sys.stderr.write("Please select a curve first")
        else:
            sys.stderr.write("Please select a curve and a shape")

    @staticmethod
    def cmdCreator():
        return OpenMayaMPx.asMPxPtr( instanceAlongCurveCommand() )