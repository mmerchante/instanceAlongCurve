Roadmap
====================

### Modeling/Animation mode

Right now, the instancing logic is tied through attribute callbacks, which are, in my opinion, pretty unreliable. This also brings a set of unresolvable issues (batch rendering doesn't update correctly node, etc.)

However, there is another way to implement the instancing logic, which is through a particle instancer node. This method would be much more efficient and would be animation friendly. The only downside to this is that it would be less flexible; e.g. instances would not be selectable, grouped, combined, etc.

So, the solution to this would be either
* a) implementing another plugin 
* b) using the instancer, with some tools to bake into a mesh, or single instances, etc.
* c) creating a weird hybrid


a) is overkill and less usable (hard to explain also), b) would be problematic when baking, because it would lose the animation flexibility of the plugin so c) seems like the reasonable solution.

Adding a Modeling/Animation mode would then change the node logic to use the attribute callbacks or the particle instancer node based on an enum.

### Density curve

Set how objects should be distributed over the curve.

### Visibility curve

Set where do objects are visible on the curve.

