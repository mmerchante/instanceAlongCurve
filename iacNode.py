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
        self.triggerUpdate = False
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

    def getCurveFn(self, curvePlug):

        if curvePlug.isConnected():
            connections = OpenMaya.MPlugArray()
            curvePlug.connectedTo(connections, True, False)
            
            if connections.length() == 1:
                return OpenMaya.MFnNurbsCurve(connections[0].node())

        return OpenMaya.MFnNurbsCurve()

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

                self.triggerUpdate = True

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
                    self.setDrawingOverride(instanceFn)

                    instObjGroupsAttr = instanceFn.attribute('message')
                    instPlugArray = OpenMaya.MPlug(trInstance, instObjGroupsAttr)
                    
                    knownInstancesPlugElement = knownInstancesPlug.elementByLogicalIndex(i)
                    mdgModifier.connect(instPlugArray, knownInstancesPlugElement)

                mdgModifier.doIt()

        # TODO: If there are more instances than needed, delete them
        # elif knownInstancesPlug.numConnectedElements() > instanceCountPlug.asInt():
        #     triggerUpdate = True
            #pdb.set_trace()


        # Update is done in the draw method to prevent being flooded with modifications from the curve callback
        if self.triggerUpdate:
            self.updateInstancePositions()

        self.triggerUpdate = False

        return OpenMaya.kUnknownParameter

    def updateInstancePositions(self):

        nodeFn = OpenMaya.MFnDependencyNode(self.thisMObject())
        knownInstancesPlug = nodeFn.findPlug(iacNode.knownInstancesAttr, True)
        inputCurvePlug = nodeFn.findPlug(iacNode.inputCurveAttr, True)

        if inputCurvePlug.isConnected():

            fnCurve = self.getCurveFn(inputCurvePlug)
            curveLength = fnCurve.length()

            connectedIndices = OpenMaya.MIntArray()
            knownInstancesPlug.getExistingArrayAttributeIndices(connectedIndices)

            connections = OpenMaya.MPlugArray()
            
            point = OpenMaya.MPoint()
            curvePointIndex = 0

            for i in connectedIndices:

                param = fnCurve.findParamFromLength(curveLength * (float(curvePointIndex) / connectedIndices.length()))
                fnCurve.getPointAtParam(param, point)

                curvePointIndex += 1

                knownPlugElement = knownInstancesPlug.elementByLogicalIndex(i)
                knownPlugElement.connectedTo(connections, True, False)
                
                for c in xrange(0, connections.length()):
                    instanceFn = OpenMaya.MFnTransform(connections[c].node())
                    instanceFn.setTranslation(OpenMaya.MVector(point), OpenMaya.MSpace.kTransform)

    def connectionMade(self, plug, otherPlug, asSrc):
        if plug.attribute() == iacNode.inputCurveAttr:
            OpenMaya.MNodeMessage.addNodeDirtyPlugCallback(otherPlug.node(), curveChangedCallback, self)
        
        return OpenMaya.kUnknownParameter

def curveChangedCallback(node, plug, self):
    self.triggerUpdate = True

def nodeCreator():
    return OpenMayaMPx.asMPxPtr( iacNode() )

def nodeInitializer():

    nAttr = OpenMaya.MFnNumericAttribute()
    msgAttributeFn = OpenMaya.MFnMessageAttribute()
    curveAttributeFn = OpenMaya.MFnTypedAttribute()

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
    
    # Input curve
    iacNode.inputCurveAttr = msgAttributeFn.create( 'inputCurve', 'curve')
    msgAttributeFn.setWritable( True )
    msgAttributeFn.setStorable( True ) 
    msgAttributeFn.setHidden( False )
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