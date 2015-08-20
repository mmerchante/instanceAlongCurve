
![Screenshot](screenshot.png)
Instance Along Curve
==================

### About
Maya Plugin for interactive instancing of shapes along curves.

Short demo at: [Youtube](https://www.youtube.com/watch?v=k4i_dZjxVr0)

### Features
* It's a dependency graph node, so it works gracefully with Maya environment.
* Instance an object by count or by distance between instances.
* Various rotation modes, including chain mode.
* Customize how instances look.
* Customize the instances transformation by ramps evaluated in curve parameter space.
* Randomize instances transformations
* Portable
* User friendly, highly flexible

### Installation
Save instanceAlongCurve.py under MAYA_PLUG_IN_PATH
 * (Linux) $HOME/maya/plug-ins
 * (Mac OS X) $HOME/Library/Preferences/Autodesk/maya/plug-ins
 * (Windows) \Users\<username>\Documents\maya\plug-ins

### Use
To use the plugin, select a curve and the shape you want to instance and go to Edit->Instance Along Curve. You can save it as a Shelf Button if you want.

### Known issues
* When batch rendering, if the node has complex logic depending on time, it may be necessary to bake the node and its children. In some renderers, the node is not being evaluated each frame.
* When the instancing mode is by distance, any change on the curve length is not immediatly reflected until a change on the instancing attributes is made.

### License
MIT
