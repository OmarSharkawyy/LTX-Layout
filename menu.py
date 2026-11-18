import nuke
from ltx_layout_studio.bridge import create


menu = nuke.menu("Nodes")
comfy = menu.findItem("ComfyUI")
if comfy is None:
    comfy = menu.addMenu("ComfyUI")

label = "LTX Layout"
if comfy.findItem(label) is None:
    index = -1
    for position, item in enumerate(comfy.items()):
        name = item.name()
        if name.startswith("LTX "):
            if name.casefold() > label.casefold():
                index = position
                break
            index = position + 1
    comfy.addCommand(label, create, index=index)
