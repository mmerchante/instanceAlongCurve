import sys
import pdb
import maya.OpenMayaMPx as OpenMayaMPx
import maya.OpenMaya as OpenMaya
import inspect
import random

kPluginNodeName = 'iacNode'
kPluginNodeClassify = 'utility/general'
kPluginNodeId = OpenMaya.MTypeId( 0x55555 ) 

defaultInstanceCount = 5

class iacNode(OpenMayaMPx.MPxLocatorNode):

    # Input attr
    inputCurveAttr = OpenMaya.MObject()
    inputTransformAttr = OpenMaya.MObject()
    instanceCountAttr = OpenMaya.MObject()
    knownInstancesAttr = OpenMaya.MObject()

    def __init__(self):
        OpenMayaMPx.MPxLocatorNode.__init__(self)

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

    def getNextAvailableLogicalIndex(self, plug):
        
        indices = OpenMaya.MIntArray()  
        max = -1
        
        if plug.isArray():  
            plug.getExistingArrayAttributeIndices(indices)
            
            for i in range(0, indices.length()):
                if(indices[i] > max):
                    max = indices[i]

        # 0 if there is no element :)
        return max + 1

    # Find original SG to reassign it to instance
    def getSG(self, dagPath):

        dagPath.extendToShape()
        fnDepNode = OpenMaya.MFnDependencyNode(dagPath.node())
        depNode = dagPath.node()

        instObjGroupsAttr = fnDepNode.attribute('instObjGroups')      
        instPlugArray = OpenMaya.MPlug(depNode, instObjGroupsAttr)
        instPlugArrayElem = instPlugArray.elementByLogicalIndex(dagPath.instanceNumber())

        if instPlugArrayElem.isConnected():
            
            connectedPlugs = OpenMaya.MPlugArray()      
            instPlugArrayElem.connectedTo(connectedPlugs, False, True)

            if connectedPlugs.length() == 1:

                sgNode = connectedPlugs[0].node()

                if(sgNode.hasFn(OpenMaya.MFn.kSet)):
                    return OpenMaya.MFnSet(sgNode)

        # No SG found, just return an empty one
        return OpenMaya.MFnSet()

    def setDrawingOverride(self, nodeFn):
        overrideEnabledPlug = nodeFn.findPlug("overrideEnabled", False)
        overrideEnabledPlug.setBool(True)

        lodPlug = nodeFn.findPlug("overrideLevelOfDetail", False)
        lodPlug.setInt(1)

    def draw(self, view, path, style, status):

        # Node fn to get plugs
        nodeFn = OpenMaya.MFnDependencyNode(self.thisMObject())
        knownInstancesPlug = nodeFn.findPlug(iacNode.knownInstancesAttr, True)
        instanceCountPlug = nodeFn.findPlug(iacNode.instanceCountAttr, True)

        # Only instance if we are missing elements
        if knownInstancesPlug.numConnectedElements() < instanceCountPlug.asInt():

            inputTransformPlug = nodeFn.findPlug(iacNode.inputTransformAttr, True)

            # Get connected input transform plugs 
            inputTransformConnectedPlugs = OpenMaya.MPlugArray()
            inputTransformPlug.connectedTo(inputTransformConnectedPlugs, True, False)

            # Find input transform
            if inputTransformConnectedPlugs.length() == 1:
                transform = inputTransformConnectedPlugs[0].node()
                transformFn = OpenMaya.MFnTransform(transform)

                # Get shading group first
                dagPath = OpenMaya.MDagPath()
                transformFn.getPath(dagPath)
                shadingGroupFn = self.getSG(dagPath)

                mdgModifier = OpenMaya.MDGModifier()

                instanceCount = instanceCountPlug.asInt() - knownInstancesPlug.numConnectedElements()

                availableIndices = self.getAvailableLogicalIndices(knownInstancesPlug, instanceCount)

                # Instance as many times as necessary
                for i in availableIndices:
                    
                    # Instance transform and reassign SG
                    trInstance = transformFn.duplicate(True, True)

                    # TODO: Handle inexistant SG
                    shadingGroupFn.addMember(trInstance)

                    instanceFn = OpenMaya.MFnTransform(trInstance)
                    instanceFn.translateBy(OpenMaya.MVector(random.random() * 5 + 10, random.random() * 5 + 10, random.random() * 5 + 10), OpenMaya.MSpace.kTransform)
                    self.setDrawingOverride(instanceFn)

                    instObjGroupsAttr = instanceFn.attribute('message')
                    instPlugArray = OpenMaya.MPlug(trInstance, instObjGroupsAttr)
                    
                    knownInstancesPlugElement = knownInstancesPlug.elementByLogicalIndex(i)
                    mdgModifier.connect(instPlugArray, knownInstancesPlugElement)

                mdgModifier.doIt()

        # TODO: If there are more instances than needed, delete them
        #elif knownInstancesPlug.numConnectedElements() > instanceCountPlug.asInt():
            #pdb.set_trace()


        #connectedIndices = OpenMaya.MIntArray()
        #knownInstancesPlug.getExistingArrayAttributeIndices(connectedIndices)
        
        #for i in range(0, connectedIndices.length()):
            #knownPlugElement = knownInstancesPlug.elementByLogicalIndex(connectedIndices[i])
            #print(knownPlugElement.asMObject())
            #instanceFn = OpenMaya.MFnTransform(knownPlugElement.asMObject())
            #instanceFn.translateBy(OpenMaya.MVector(random.random(), random.random(), random.random()), OpenMaya.MSpace.kTransform)

        return OpenMaya.kUnknownParameter

def nodeCreator():
    return OpenMayaMPx.asMPxPtr( iacNode() )

def nodeInitializer():

    nAttr = OpenMaya.MFnNumericAttribute()
    geometryAttributeFn = OpenMaya.MFnGenericAttribute ()
    curveAttributeFn = OpenMaya.MFnTypedAttribute()
    msgAttributeFn = OpenMaya.MFnMessageAttribute()

    iacNode.inputTransformAttr = msgAttributeFn.create("inputTransform", "it")
    msgAttributeFn.setWritable( True )
    msgAttributeFn.setStorable( True )
    msgAttributeFn.setHidden( False )
    iacNode.addAttribute( iacNode.inputTransformAttr )

    iacNode.knownInstancesAttr = msgAttributeFn.create("knownInstances", "ki")
    msgAttributeFn.setWritable( True )    
    msgAttributeFn.setStorable( True )    
    msgAttributeFn.setHidden( True )  
    msgAttributeFn.setArray( True )  
    msgAttributeFn.setDisconnectBehavior(OpenMaya.MFnAttribute.kDelete) # Very important :)
    iacNode.addAttribute( iacNode.knownInstancesAttr )
    
    ## Input instance count    
    iacNode.instanceCountAttr = nAttr.create("instanceCount", "iic", OpenMaya.MFnNumericData.kInt, defaultInstanceCount)
    nAttr.setWritable( True )
    nAttr.setStorable( True )
    nAttr.setHidden( False )
    iacNode.addAttribute( iacNode.instanceCountAttr)
    
    ## Input curve
    iacNode.inputCurveAttr = curveAttributeFn.create( 'inputCurve', 'iC', OpenMaya.MFnData.kNurbsCurve)
    curveAttributeFn.setWritable( True )
    curveAttributeFn.setStorable( True ) 
    curveAttributeFn.setHidden( True )
    iacNode.addAttribute( iacNode.inputCurveAttr )

def initializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        mplugin.registerNode( kPluginNodeName, kPluginNodeId, nodeCreator,
                              nodeInitializer, OpenMayaMPx.MPxNode.kLocatorNode, kPluginNodeClassify )
    except:
        sys.stderr.write( 'Failed to register node: ' + kPluginNodeName )
        raise
    
def uninitializePlugin( mobject ):
    mplugin = OpenMayaMPx.MFnPlugin( mobject )
    try:
        mplugin.deregisterNode( kPluginNodeId )
    except:
        sys.stderr.write( 'Failed to deregister node: ' + kPluginNodeName )
        raise