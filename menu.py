import nuke
from ltx_layout_studio.bridge import create

nuke.menu("Nodes").addCommand("ComfyUI/LTX Layout", create)
