"""Image edit model helper nodes for LX-Nodes."""

from .boogu_image_edit import LXBooguImageEdit
from .flux2_kontext_image_edit import LXFlux2KontextImageEdit
from .flux2_klein_image_edit import LXFlux2KleinImageEdit
from .qwen21_edit_canvas import LXQwen21EditCanvas
from .qwen21_multi_image_edit import LXQwen21MultiImageEdit
from .qwen_image_edit import LXQwenImageEdit

NODE_CLASS_MAPPINGS = {
    "LXBooguImageEdit": LXBooguImageEdit,
    "LXFlux2KontextImageEdit": LXFlux2KontextImageEdit,
    "LXFlux2KleinImageEdit": LXFlux2KleinImageEdit,
    "LXQwen21EditCanvas": LXQwen21EditCanvas,
    "LXQwen21MultiImageEdit": LXQwen21MultiImageEdit,
    "LXQwenImageEdit": LXQwenImageEdit,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "LXBooguImageEdit": "Boogu Image Edit",
    "LXFlux2KontextImageEdit": "Flux2 Kontext Image Edit",
    "LXFlux2KleinImageEdit": "Flux2 Klein Image Edit",
    "LXQwen21EditCanvas": "Qwen 2.1 高分辨率编辑画布",
    "LXQwen21MultiImageEdit": "Qwen 2.1 多图编辑画布",
    "LXQwenImageEdit": "Qwen Image Edit",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS"]
