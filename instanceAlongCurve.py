import sys
import pdb
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

# NEXT STEPS: 
#   - Reintegrate old instancing logic with new arch
#   - Convert all display parameters into array attributes

# Ideas:
#   - orientation constraints: set a fixed axis?
#   - twisting
#   - scale modes
#   - modulate attributes (pos, rot, scale) along curve's parameter space through user curves

class instanceAlongCurveLocator(OpenMayaMPx.MPxLocatorNode):

    # Simple container class for compound vector attributes
    class Vector3CompoundAttribute(object):

        def __init__(self):            
            self.compound = OpenMaya.MObject()
            self.x = OpenMaya.MObject()
            self.y = OpenMaya.MObject()
            self.z = OpenMaya.MObject()

    # Input attr
    inputCurveAttr = OpenMaya.MObject()
    inputTransformAttr = OpenMaya.MObject()
    inputShadingGroupAttr = OpenMaya.MObject()
    inputTimeAttr = OpenMaya.MObject()

    instanceCountAttr = OpenMaya.MObject()
    instancingModeAttr = OpenMaya.MObject()
    instanceLengthAttr = OpenMaya.MObject()
    maxInstancesByLengthAttr = OpenMaya.MObject()

    knownInstancesAttr = OpenMaya.MObject()
    displayTypeAttr = OpenMaya.MObject()
    bboxAttr = OpenMaya.MObject()

    orientationModeAttr = OpenMaya.MObject()

    # Output vectors
    outputTranslationAttr = Vector3CompoundAttribute()
    outputRotationAttr = Vector3CompoundAttribute()
    outputScaleAttr = Vector3CompoundAttribute()

    def __init__(self):
        OpenMayaMPx.MPxLocatorNode.__init__(self)

    def postConstructor(self):
        OpenMaya.MFnDependencyNode(self.thisMObject()).setName("instanceAlongCurveLocatorShape#")

    # Helper function to get an array of available logical indices from the sparse array
    # def getAvailableLogicalIndices(self, plug, numIndices):
        
    #     # Allocate and initialize
    #     outIndices = OpenMaya.MIntArray(numIndices)
    #     indices = OpenMaya.MIntArray(plug.numElements())
    #     plug.getExistingArrayAttributeIndices(indices)

    #     currentAvailableIndex = 0
    #     indicesFound = 0

    #     # Assuming indices are SORTED :)
    #     for i in indices:

    #         connectedPlug = plug.elementByLogicalIndex(i).isConnected()

    #         # Iteratively find available indices in the sparse array
    #         while i > currentAvailableIndex:
    #             outIndices[indicesFound] = currentAvailableIndex
    #             indicesFound += 1
    #             currentAvailableIndex += 1

    #         # Check against this index, add it if it is not connected
    #         if i == currentAvailableIndex and not connectedPlug:
    #             outIndices[indicesFound] = currentAvailableIndex
    #             indicesFound += 1

    #         currentAvailableIndex += 1

    #         if indicesFound == numIndices:
    #             return outIndices

    #     # Fill remaining expected indices
    #     for i in xrange(indicesFound, numIndices):
    #         outIndices[i] = currentAvailableIndex
    #         currentAvailableIndex += 1

    #     return outIndices

    # def updateDrawingOverrides(self):
    #     knownInstancesPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.knownInstancesAttr)
    #     drawMode = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.displayTypeAttr).asInt()
    #     useBBox = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.bboxAttr).asBool()

    #     connections = OpenMaya.MPlugArray()

    #     for i in xrange(knownInstancesPlug.numConnectedElements()):
    #         knownPlugElement = knownInstancesPlug.elementByPhysicalIndex(i)
    #         knownPlugElement.connectedTo(connections, True, False)
            
    #         for c in xrange(0, connections.length()):
    #             instanceFn = OpenMaya.MFnTransform(connections[c].node())
    #             self.setDrawingOverride(instanceFn, drawMode, useBBox)

    # def setDrawingOverride(self, nodeFn, drawMode, useBBox):
    #     overrideEnabledPlug = nodeFn.findPlug("overrideEnabled", False)
    #     overrideEnabledPlug.setBool(True)

    #     displayPlug = nodeFn.findPlug("overrideDisplayType", False)
    #     displayPlug.setInt(drawMode)

    #     lodPlug = nodeFn.findPlug("overrideLevelOfDetail", False)
    #     lodPlug.setInt(useBBox)

    # def assignShadingGroup(self, fnSet, fnDagNode):
    #     # Easiest, cleanest way seems to be calling MEL.
    #     # sets command handles everything, even nested instanced dag paths
    #     mdgm = OpenMaya.MDGModifier()
    #     mdgm.commandToExecute("sets -e -fe " + fnSet.name() + " " + fnDagNode.name())
    #     mdgm.doIt()

    # # Find original SG to reassign it to instance
    # def getSG(self):
    #     inputSGPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputShadingGroupAttr)
    #     sgNode = self.getSingleSourceObjectFromPlug(inputSGPlug)

    #     if sgNode is not None and sgNode.hasFn(OpenMaya.MFn.kSet):
    #         return OpenMaya.MFnSet(sgNode)

    #     return None

    # def getSingleSourceObjectFromPlug(self, plug):
    #     if plug.isConnected():

    #         # Get connected input plugs
    #         connections = OpenMaya.MPlugArray()
    #         plug.connectedTo(connections, True, False)

    #         # Find input transform
    #         if connections.length() == 1:
    #             return connections[0].node()

    #     return None

    # def getInputTransformFn(self):
    #     inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
    #     transform = self.getSingleSourceObjectFromPlug(inputTransformPlug)

    #     if transform is not None and transform.hasFn(OpenMaya.MFn.kTransform):

    #             # Get Fn from a DAG path to get the world transformations correctly
    #             path = OpenMaya.MDagPath()
    #             trFn = OpenMaya.MFnDagNode(transform)
    #             trFn.getPath(path)

    #             return OpenMaya.MFnTransform(path)

    #     return None

    # def getCurveFn(self):
    #     inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)
    #     curve = self.getSingleSourceObjectFromPlug(inputCurvePlug)

    #     if curve is not None:
    #         # Get Fn from a DAG path to get the world transformations correctly
    #         path = OpenMaya.MDagPath()
    #         trFn = OpenMaya.MFnDagNode(curve)
    #         trFn.getPath(path)

    #         path.extendToShape()

    #         if path.node().hasFn(OpenMaya.MFn.kNurbsCurve):
    #             return OpenMaya.MFnNurbsCurve(path)

    #     return None

    def draw(self, view, path, style, status):

        # try:
        #     self.updateInstanceConnections(path)
        # except:
        #     sys.stderr.write('Failed trying to update locator. stack trace: \n')
        #     sys.stderr.write(traceback.format_exc())

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

    # # Calculate expected instances by the instancing mode
    # def getInstanceCountByMode(self):
    #     instancingModePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instancingModeAttr)
    #     inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)

    #     if inputCurvePlug.isConnected() and instancingModePlug.asInt() == 1:
    #         instanceLengthPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instanceLengthAttr)
    #         maxInstancesByLengthPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.maxInstancesByLengthAttr)
    #         curveFn = self.getCurveFn()
    #         return min(maxInstancesByLengthPlug.asInt(), int(curveFn.length() / instanceLengthPlug.asFloat()))

    #     instanceCountPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.instanceCountAttr)
    #     return instanceCountPlug.asInt()

    # def updateInstanceConnections(self, path):

    #     # If the locator is being instanced, just stop updating its children.
    #     # This is to prevent losing references to the locator instances' children
    #     # If you want to instance this locator, set everything before
    #     if OpenMaya.MFnDagNode(self.thisMObject()).isInstanced():
    #         return OpenMaya.kUnknownParameter

    #     expectedInstanceCount = self.getInstanceCountByMode()
    #     knownInstancesPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.knownInstancesAttr)

    #     # Only instance if we are missing elements
    #     if knownInstancesPlug.numConnectedElements() < expectedInstanceCount:

    #         inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)

    #         # Get connected input transform plugs 
    #         inputTransformConnectedPlugs = OpenMaya.MPlugArray()
    #         inputTransformPlug.connectedTo(inputTransformConnectedPlugs, True, False)

    #         # Find input transform
    #         if inputTransformConnectedPlugs.length() == 1:
    #             transform = inputTransformConnectedPlugs[0].node()
    #             transformFn = OpenMaya.MFnTransform(transform)

    #             drawMode = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.displayTypeAttr).asInt()
    #             useBBox = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.bboxAttr).asBool()

    #             # Get shading group first
    #             dagPath = OpenMaya.MDagPath()
    #             transformFn.getPath(dagPath)
    #             shadingGroupFn = self.getSG()


    #             instanceCount = expectedInstanceCount - knownInstancesPlug.numConnectedElements()
    #             availableIndices = self.getAvailableLogicalIndices(knownInstancesPlug, instanceCount)

    #             # Note: knownInstances (TODO remove) indices MAY not be the same as the output matrix array
    #             # For now, we are assuming the are both handling exactly the same
    #             outputTransformationsArrayPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.outputMatricesArrayAttr)

    #             # Consider path for instances!
    #             nodeFn = OpenMaya.MFnDagNode(path.transform())

    #             # Instance as many times as necessary
    #             for i in availableIndices:
                    
    #                 # Instance transform
    #                 # InstanceLeaf must be set to False to prevent crashes :)
    #                 trInstance = transformFn.duplicate(True, False)

    #                 # Parent new instance
    #                 nodeFn.addChild(trInstance)

    #                 # Recursively assign shading group
    #                 if shadingGroupFn is not None:
    #                     self.assignShadingGroup(shadingGroupFn, OpenMaya.MFnDagNode(trInstance))

    #                 instanceFn = OpenMaya.MFnTransform(trInstance)
    #                 self.setDrawingOverride(instanceFn, drawMode, useBBox)

    #                 instObjGroupsAttr = instanceFn.attribute('message')
    #                 instPlugArray = OpenMaya.MPlug(trInstance, instObjGroupsAttr)

    #                 instTransformationAttr = instanceFn.attribute('worldMatrix')
    #                 instTransformationPlug = OpenMaya.MPlug(trInstance, instTransformationAttr)
    #                 instTransformationPlugElement = instTransformationPlug.elementByLogicalIndex(5)
                    
    #                 knownInstancesPlugElement = knownInstancesPlug.elementByLogicalIndex(i)
    #                 outputTransformationPlugElement = outputTransformationsArrayPlug.elementByLogicalIndex(i)

    #                 mdgModifier = OpenMaya.MDagModifier()
    #                 # mdgModifier.connect(instPlugArray, knownInstancesPlugElement)
    #                 mdgModifier.connect(outputTransformationPlugElement, instTransformationPlugElement)
    #                 mdgModifier.doIt()

    #     # Remove instances if necessary
    #     elif knownInstancesPlug.numConnectedElements() > expectedInstanceCount:

    #         mdgModifier = OpenMaya.MDGModifier()
    #         connections = OpenMaya.MPlugArray()
            
    #         numConnectedElements = knownInstancesPlug.numConnectedElements()
    #         toRemove = knownInstancesPlug.numConnectedElements() - expectedInstanceCount

    #         for i in xrange(toRemove):

    #             knownPlugElement = knownInstancesPlug.connectionByPhysicalIndex(numConnectedElements - 1 - i)
    #             knownPlugElement.connectedTo(connections, True, False)
                
    #             for c in xrange(connections.length()):
    #                 node = connections[c].node()
    #                 mdgModifier.disconnect(connections[c], knownPlugElement)
    #                 mdgModifier.deleteNode(node)

    #         mdgModifier.doIt()

    #     return OpenMaya.kUnknownParameter

    # def updateInstancePositions(self):

    #     knownInstancesPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.knownInstancesAttr)
    #     inputCurvePlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputCurveAttr)
    #     fnCurve = self.getCurveFn()

    #     if fnCurve is not None:

    #         rotMode = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.orientationModeAttr).asInt()

    #         inputTransformPlug = OpenMaya.MPlug(self.thisMObject(), instanceAlongCurveLocator.inputTransformAttr)
    #         inputTransformRotation = OpenMaya.MQuaternion()

    #         if inputTransformPlug.isConnected():
    #             self.getInputTransformFn().getRotation(inputTransformRotation, OpenMaya.MSpace.kWorld)

    #         curveLength = fnCurve.length()

    #         numConnectedElements = knownInstancesPlug.numConnectedElements()
    #         point = OpenMaya.MPoint()
    #         connections = OpenMaya.MPlugArray()

    #         # TODO: let the user decide forward axis?
    #         startOrientation = OpenMaya.MVector(0.0, 0.0, 1.0)
    #         curvePointIndex = 0

    #         shadingGroupFn = self.getSG()

    #         for i in xrange(numConnectedElements):

    #             param = fnCurve.findParamFromLength(curveLength * (float(curvePointIndex) / numConnectedElements))
    #             fnCurve.getPointAtParam(param, point, OpenMaya.MSpace.kWorld)

    #             rot = OpenMaya.MQuaternion()

    #             if rotMode == 1:
    #                 rot = inputTransformRotation;
    #             elif rotMode == 2:
    #                 normal = fnCurve.normal(param, OpenMaya.MSpace.kWorld)
    #                 rot = startOrientation.rotateTo(normal)
    #             elif rotMode == 3:
    #                 tangent = fnCurve.tangent(param, OpenMaya.MSpace.kWorld)
    #                 rot = startOrientation.rotateTo(tangent)

    #             curvePointIndex += 1

    #             knownPlugElement = knownInstancesPlug.elementByPhysicalIndex(i)
    #             knownPlugElement.connectedTo(connections, True, False)

    #             instanceDagPath = OpenMaya.MDagPath()
                
    #             for c in xrange(0, connections.length()):
    #                 # Is there a nicer way to do this? dagPath is needed to use kWorld
    #                 instanceFn = OpenMaya.MFnTransform(connections[c].node())
    #                 instanceFn.getPath(instanceDagPath)
    #                 instanceFn = OpenMaya.MFnTransform(instanceDagPath)

    #                 instanceFn.setTranslation(OpenMaya.MVector(point), OpenMaya.MSpace.kWorld)
    #                 instanceFn.setRotation(rot, OpenMaya.MSpace.kWorld)


    def updateInstancePositions(self, curveFn, dataBlock):
            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            translateArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputTranslationAttr.compound)

            for i in xrange(translateArrayHandle.elementCount()):
                param = curveFn.findParamFromLength(curveLength * (i / float(translateArrayHandle.elementCount())))
                curveFn.getPointAtParam(param, point)

                translateHandle = translateArrayHandle.outputValue()
                translateHandle.set3Float(point.x, point.y, point.z)

                if i < translateArrayHandle.elementCount() - 1:
                    translateArrayHandle.next()

            translateArrayHandle.setAllClean()

    def updateInstanceRotations(self, curveFn, dataBlock):
            point = OpenMaya.MPoint()
            curveLength = curveFn.length()
            rotationArrayHandle = dataBlock.outputArrayValue(instanceAlongCurveLocator.outputRotationAttr.compound)

            startOrientation = OpenMaya.MVector(0.0, 0.0, 1.0)

            for i in xrange(rotationArrayHandle.elementCount()):

                param = curveFn.findParamFromLength(curveLength * (i / float(rotationArrayHandle.elementCount())))
                tangent = curveFn.tangent(param)
                rot = startOrientation.rotateTo(tangent).asEulerRotation().asVector()

                rotationHandle = rotationArrayHandle.outputValue()
                rotationHandle.set3Float(rot.x, rot.y, rot.z)

                if i < rotationArrayHandle.elementCount() - 1:
                    rotationArrayHandle.next()

            rotationArrayHandle.setAllClean()

    def compute(self, plug, dataBlock):

        try:
            timeDataHandle = dataBlock.inputValue( instanceAlongCurveLocator.inputTimeAttr )
            time = timeDataHandle.asTime().value()

            curveDataHandle = dataBlock.inputValue(instanceAlongCurveLocator.inputCurveAttr)
            curveFn = OpenMaya.MFnNurbsCurve(curveDataHandle.asNurbsCurveTransformed())

            print "Computing! " + plug.info()

            self.updateInstancePositions(curveFn, dataBlock)
            self.updateInstanceRotations(curveFn, dataBlock)

            dataBlock.setClean(plug)

        except:
            sys.stderr.write('Failed trying to compute locator. stack trace: \n')
            sys.stderr.write(traceback.format_exc())
            return OpenMaya.kUnknownParameter

    @staticmethod
    def nodeCreator():
        return OpenMayaMPx.asMPxPtr( instanceAlongCurveLocator() )

    @classmethod
    def addCompoundVector3Attribute(cls, compoundAttribute, attributeName):

        nAttr = OpenMaya.MFnNumericAttribute()

        compoundAttribute.x = nAttr.create(attributeName + "X", attributeName + "X", OpenMaya.MFnNumericData.kFloat)    
        nAttr.setWritable( False )
        cls.addAttribute(compoundAttribute.x)

        compoundAttribute.y = nAttr.create(attributeName + "Y", attributeName + "Y", OpenMaya.MFnNumericData.kFloat)
        nAttr.setWritable( False )
        cls.addAttribute(compoundAttribute.y)

        compoundAttribute.z = nAttr.create(attributeName + "Z", attributeName + "Z", OpenMaya.MFnNumericData.kFloat)
        nAttr.setWritable( False )
        cls.addAttribute(compoundAttribute.z)

        # Output compound
        compoundAttribute.compound = nAttr.create(attributeName, attributeName,
                                     compoundAttribute.x, compoundAttribute.y, compoundAttribute.z)
        nAttr.setWritable( False )
        nAttr.setArray( True )
        nAttr.setUsesArrayDataBuilder( True )
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

        node.knownInstancesAttr = msgAttributeFn.create("knownInstances", "ki")    
        msgAttributeFn.setArray( True )  
        msgAttributeFn.setDisconnectBehavior(OpenMaya.MFnAttribute.kDelete) # Very important :)
        node.addAttribute( node.knownInstancesAttr )

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
        nAttr.setChannelBox( True )
        nAttr.setConnectable( False )
        node.addAttribute( node.instanceCountAttr)

        ## Max instances when defined by instance length
        node.maxInstancesByLengthAttr = nAttr.create("maxInstancesByLength", "mibl", OpenMaya.MFnNumericData.kInt, 50)
        nAttr.setMin(0)
        nAttr.setSoftMax(200)
        nAttr.setChannelBox( True )
        nAttr.setConnectable( False )
        node.addAttribute( node.maxInstancesByLengthAttr)

        # Length between instances
        node.instanceLengthAttr = nAttr.create("instanceLength", "ilength", OpenMaya.MFnNumericData.kFloat, 1.0)
        nAttr.setMin(0.01)
        nAttr.setSoftMax(1.0)
        nAttr.setChannelBox( True )
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
        enumFn.setDefault("Tangent")
        node.addAttribute( node.orientationModeAttr )

        node.bboxAttr = nAttr.create('instanceBoundingBox', 'ibb', OpenMaya.MFnNumericData.kBoolean, False)
        node.addAttribute( node.bboxAttr )

        # Output attributes
        node.addCompoundVector3Attribute(node.outputTranslationAttr, "outputTranslation")        
        node.addCompoundVector3Attribute(node.outputRotationAttr, "outputRotation")
        # node.addCompoundVector3Attribute(node.outputScaleAttr, "outputScale")

        node.attributeAffects( node.inputTimeAttr, node.outputTranslationAttr.compound )
        node.attributeAffects( node.inputCurveAttr, node.outputTranslationAttr.compound )

        node.attributeAffects( node.inputTimeAttr, node.outputRotationAttr.compound )
        node.attributeAffects( node.inputCurveAttr, node.outputRotationAttr.compound )

def initializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        # Register command
        # mplugin.registerCommand( kPluginCmdName, instanceAlongCurveCommand.cmdCreator )

        # if OpenMaya.MGlobal.mayaState() != OpenMaya.MGlobal.kBatch:
        #     mplugin.addMenuItem("Instance Along Curve", "MayaWindow|mainEditMenu", kPluginCmdName, "")

            # Register AE template
            # pm.callbacks(addCallback=loadAETemplateCallback, hook='AETemplateCustomContent', owner=kPluginNodeName)

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
        # mplugin.deregisterCommand( kPluginCmdName )
        mplugin.deregisterNode( kPluginNodeId )
    except:
        sys.stderr.write( 'Failed to deregister plugin instanceAlongCurve')
        raise

# ###############
# # AE TEMPLATE #
# ###############
# def loadAETemplateCallback(nodeName):
#     AEinstanceAlongCurveLocatorTemplate(nodeName)

# class AEinstanceAlongCurveLocatorTemplate(pm.ui.AETemplate):

#     def addControl(self, control, label=None, **kwargs):
#         pm.ui.AETemplate.addControl(self, control, label=label, **kwargs)

#     def beginLayout(self, name, collapse=True):
#         pm.ui.AETemplate.beginLayout(self, name, collapse=collapse)

#     def __init__(self, nodeName):
#         pm.ui.AETemplate.__init__(self,nodeName)
#         self.thisNode = None
#         self.node = pm.PyNode(self.nodeName)

#         if self.node.type() == kPluginNodeName:
#             self.beginScrollLayout()
#             self.beginLayout("Instance Along Curve Settings" ,collapse=0)

#             self.addControl("instancingMode", label="Instancing Mode", changeCommand=self.onInstanceModeChanged)
#             self.addControl("instanceCount", label="Count")
#             self.addControl("instanceLength", label="Distance")
#             self.addControl("maxInstancesByLength", label="Max Instances")
            
#             self.addSeparator()

#             self.addControl("orientationMode", label="Orientation Mode")

#             self.addSeparator()
            
#             self.addControl("instanceDisplayType", label="Instance Display Type")
#             self.addControl("instanceBoundingBox", label="Use bounding box")
            
#             self.addSeparator()
            
#             self.addControl("inputCurve", label="Input curve")
#             self.addControl("inputTransform", label="Input object")
#             self.addControl("inputShadingGroup", label="Shading Group")
#             self.addExtraControls()

#             self.endLayout()
#             self.endScrollLayout()

#     def onInstanceModeChanged(self, nodeName):
#         if pm.PyNode(nodeName).type() == kPluginNodeName:
#             nodeAttr = pm.PyNode(nodeName + ".instancingMode")
#             mode = nodeAttr.get("instancingMode")
#             self.dimControl(nodeName, "instanceLength", mode == 0)
#             self.dimControl(nodeName, "maxInstancesByLength", mode == 0)
#             self.dimControl(nodeName, "instanceCount", mode == 1)
#             # TODO: dim everything if there is no curve or transform

# # Command
# class instanceAlongCurveCommand(OpenMayaMPx.MPxCommand):

#     def __init__(self):
#         OpenMayaMPx.MPxCommand.__init__(self)
#         self.mUndo = []

#     def isUndoable(self):
#         return True

#     def undoIt(self): 
#         OpenMaya.MGlobal.displayInfo( "Undo: instanceAlongCurveCommand\n" )

#         # Reversed for undo :)
#         for m in reversed(self.mUndo):
#             m.undoIt()

#     def redoIt(self): 
#         OpenMaya.MGlobal.displayInfo( "Redo: instanceAlongCurveCommand\n" )
        
#         for m in self.mUndo:
#             m.doIt()

#     def hasShapeBelow(self, dagPath):

#         sutil = OpenMaya.MScriptUtil()
#         uintptr = sutil.asUintPtr()
#         sutil.setUint(uintptr , 0)

#         dagPath.numberOfShapesDirectlyBelow(uintptr)

#         return sutil.getUint(uintptr) > 0

#     def findShadingGroup(self, dagPath):

#         # Search in children first before extending to shape
#         for child in xrange(dagPath.childCount()):
#             childDagPath = OpenMaya.MDagPath()
#             fnDagNode = OpenMaya.MFnDagNode(dagPath.child(child))
#             fnDagNode.getPath(childDagPath)

#             fnSet = self.findShadingGroup(childDagPath)

#             if fnSet is not None:
#                 return fnSet

#         if self.hasShapeBelow(dagPath):
#             dagPath.extendToShape()
#             fnDepNode = OpenMaya.MFnDependencyNode(dagPath.node())

#             instPlugArray = fnDepNode.findPlug("instObjGroups")
#             instPlugArrayElem = instPlugArray.elementByLogicalIndex(dagPath.instanceNumber())

#             if instPlugArrayElem.isConnected():
#                 connectedPlugs = OpenMaya.MPlugArray()      
#                 instPlugArrayElem.connectedTo(connectedPlugs, False, True)

#                 if connectedPlugs.length() == 1:
#                     sgNode = connectedPlugs[0].node()

#                     if sgNode.hasFn(OpenMaya.MFn.kSet):
#                         return OpenMaya.MFnSet(sgNode)

#         return None
        
#     def doIt(self,argList):
        
#         try:
#             list = OpenMaya.MSelectionList()
#             OpenMaya.MGlobal.getActiveSelectionList(list)

#             if list.length() == 2:
#                 curveDagPath = OpenMaya.MDagPath()
#                 list.getDagPath(0, curveDagPath)
#                 curveDagPath.extendToShape()

#                 shapeDagPath = OpenMaya.MDagPath()
#                 list.getDagPath(1, shapeDagPath)           

#                 if(curveDagPath.node().hasFn(OpenMaya.MFn.kNurbsCurve)):

#                     # We need the curve transform
#                     curveTransformFn = OpenMaya.MFnDagNode(curveDagPath.transform())
#                     curveTransformPlug = curveTransformFn.findPlug("message", True)

#                     # We need the shape's transform too
#                     transformFn = OpenMaya.MFnDagNode(shapeDagPath.transform())
#                     transformMessagePlug = transformFn.findPlug("message", True)

#                     shadingGroupFn = self.findShadingGroup(shapeDagPath)

#                     # Create node first
#                     mdagModifier = OpenMaya.MDagModifier()
#                     self.mUndo.append(mdagModifier)
#                     newNode = mdagModifier.createNode(kPluginNodeId)
#                     mdagModifier.doIt()

#                     # Assign new correct name and select new locator
#                     newNodeFn = OpenMaya.MFnDagNode(newNode)
#                     newNodeFn.setName("instanceAlongCurveLocator#")

#                     # Get the node shape
#                     nodeShapeDagPath = OpenMaya.MDagPath()
#                     newNodeFn.getPath(nodeShapeDagPath)
#                     nodeShapeDagPath.extendToShape()
#                     newNodeFn = OpenMaya.MFnDagNode(nodeShapeDagPath)

#                     OpenMaya.MGlobal.clearSelectionList()
#                     msel = OpenMaya.MSelectionList()
#                     msel.add(nodeShapeDagPath)
#                     OpenMaya.MGlobal.setActiveSelectionList(msel)

#                     # Connect :D
#                     mdgModifier = OpenMaya.MDGModifier()
#                     self.mUndo.append(mdgModifier)               
#                     mdgModifier.connect(curveTransformPlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputCurveAttr))
#                     mdgModifier.connect(transformMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputTransformAttr))

#                     if shadingGroupFn is not None:
#                         shadingGroupMessagePlug = shadingGroupFn.findPlug("message", True)
#                         mdgModifier.connect(shadingGroupMessagePlug, newNodeFn.findPlug(instanceAlongCurveLocator.inputShadingGroupAttr))

#                     mdgModifier.doIt()
                    
#                 else:
#                     sys.stderr.write("Please select a curve first")
#             else:
#                 sys.stderr.write("Please select a curve and a shape")
#         except:
#             sys.stderr.write('Failed trying to create locator. stack trace: \n')
#             sys.stderr.write(traceback.format_exc())

#     @staticmethod
#     def cmdCreator():
#         return OpenMayaMPx.asMPxPtr( instanceAlongCurveCommand() )