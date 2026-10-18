# Context

The Blender-RCT-Graphics is a blender add-on for designing objects for the OpenRCT2 game. It features:

- A setup with a directional light and a camera
- It renders 4 views, which can be export to an object
- It also supports animated objects
- It can create large objects using tiles properly
- It supports the recolorable colours

This add-on is only compatible with Blender 2.79, and does not work with the newer versions of Blender.
You can look up at the OpenRCT2 C++ code in the OpenRCT2 folder.

# Goal

The goal is to do a plugin similar to Blender-RCT-Graphics, but compatible with the newer version of Blender, using the Cycles renderer, while making sure that the style of the rendered graphics look similar to the ones in the original game. I have personnally tried this in the past, but I had difficulties with the anti-aliasing options; the old Blender render, when the anti-aliasing was enabled, only applied anti-aliasing on the object, it didn't smoothed the edges.

Also, in the examples folder, all the sprites from the original game and its expansion packs are present. 
Let's look at the tree in 0.png: it has a dark outline; maybe there should be a postprocessing option in Blender that applies the outline to replicate this style...

The original add-on used ImageMagick for the post-processing commands; it would be ideal to get rid of it and only use Python libraries inside Blender for those operations.

In the examples, the walls only have 2 possible directions.

In the addon, there should be a tool to align easily the objects; for example, when you stack walls in the game, the alignment is very important otherwise you will see clipping. Maybe there should be a post-processing step that actually test repeating the objects on the different axis and let the viewer see if they properly align, otherwise the user would have to manually edit the json's offset everytime, it is very tedious. Propose something that would automate this. It is the same thing with base blocks, rooves, etc. For example, 10.png for a base block and 161.png for a roof.