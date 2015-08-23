[![](http://mmerchante.github.io/instanceAlongCurve/resources/header.png)](https://www.youtube.com/watch?v=k4i_dZjxVr0)
[Instance Along Curve](http://mmerchante.github.io/instanceAlongCurve)
==================

Maya API plugin developed in Python that tries to simplify the process of instancing various objects along a curve. The plugin essentially creates a new dependency graph node called instanceAlongCurveLocator, which handles all the necessary logic. It also includes a node creation command and an Attribute Editor template for a very familiar and user friendly interface.

Short demo at: [Youtube](https://www.youtube.com/watch?v=k4i_dZjxVr0)

#### Difference with other approaches

Because it is a DG node that is recomputed each time Maya considers necessary, there is no need to execute manual scripts or hacks or custom windows to update the instances. Also, it is very efficient in updating each instance, because every relevant instance attribute is connected to the locator, and only recomputes what is needed.

However, Maya makes instancing objects from a plugin node **very** difficult, so there are some known limitations.

### Features
* It's a dependency graph node, so it works gracefully with the Maya environment.
* Instance an object by count or by distance between instances.
* Various rotation modes, including chain mode.
* Customize the instances transformation by ramps evaluated in curve parameter space.
* Customize the ramps' offset with keys or expressions for animations.
* Customize how instances look in viewport.
* Randomize instances transformations.
* Portable.
* User friendly, highly flexible.

### Installation
Save instanceAlongCurve.py under MAYA_PLUG_IN_PATH
 * (Linux) $HOME/maya/plug-ins
 * (Mac OS X) $HOME/Library/Preferences/Autodesk/maya/plug-ins
 * (Windows) \\Users\\\<**username**\>\\Documents\\maya\\plug-ins

### Instructions
To use the plugin, select a curve first and the shape you want to instance and go to Edit->Instance Along Curve. You can save it as a Shelf Button if you want.

### Known issues
* When batch rendering, if the node has complex logic depending on time, it may be necessary to bake the node and its children. In some renderers, the node is not being evaluated each frame.
* When the instancing mode is by distance, any change on the curve length is not immediatly reflected until a change on the instancing attributes is made.

### License
MIT
