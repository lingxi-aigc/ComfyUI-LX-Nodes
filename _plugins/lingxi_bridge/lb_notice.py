from ..categories import LX_RELAY_CATEGORY


class LingxiBridgeNotice:
    SEARCH_ALIASES = ("lx", "LX", "灵犀", "API配置说明", "中转站说明", "帮助", "notice")

    MESSAGE = (
        "Lingxi Bridge 使用指南\n"
        "\n"
        "一、选择中转站\n"
        "在下拉框选择预设中转站，也可手动填写自定义接口地址。\n"
        "  - https://grsaiapi.com（Grsai，推荐首选）\n"
        "  - https://yunwu.ai（Yunwu）\n"
        "  - https://www.runninghub.cn（RunningHub）\n"
        "\n"
        "二、选择平台\n"
        "\n"
        "banana-pro\n"
        '  定位：专业级高画质旗舰，追求"慢而精"的最终出图效果\n'
        "  核心优势：细节、光影、质感最强，擅长复杂构图与高品质人像/写实场景\n"
        "  适合：商业主视觉、印刷级输出、复杂多元素合成等对画质要求极高的任务\n"
        "\n"
        "banana-2\n"
        "  定位：极速性价比之王，在接近 Pro 画质的基础上实现最快生成速度\n"
        "  核心优势：独家支持 1:4 / 4:1 等超宽/超窄极端比例，生成速度最快，价格最低\n"
        "  适合：大批量横版/竖版素材、电影级宽幅、短视频全屏、预算敏感型项目\n"
        "\n"
        "gpt-image2\n"
        "  定位：文字渲染与逻辑推理最强的编辑型模型，擅长图文结合与精准修改\n"
        '  核心优势：文字渲染准确率高，对复杂布局、UI、多语言排版理解更深；'
        "图生图、局部重绘等编辑能力突出\n"
        "  适合：海报、Banner、UI设计、含文字的商业素材、需要多次修改的创作流程\n"
        "\n"
        "三、选择接口格式\n"
        "根据当前选中的中转站选择对应接口格式，平台会自动筛选适配的格式与模型。\n"
        "\n"
        "四、选择模型\n"
        "可在下拉框选用预设模型，也可手动填写自定义模型名称。\n"
        "\n"
        "模型后缀说明（以各中转站官方说明为准）：\n"
        "\n"
        "Grsai 中转站（grsaiapi.com）：\n"
        "  - 无后缀：标准版\n"
        "  - -cl：更稳定，成功率更高，费用更贵\n"
        "  - -vt：4K 质量更好，高峰期可能不稳定\n"
        "  - -vip：VIP 通道\n"
        "\n"
        "RunningHub 中转站（runninghub.cn）：\n"
        "  - 无后缀：非官方通道\n"
        "  - -official：官方模型，更稳定\n"
        "\n"
        "五、优先级规则\n"
        "  - custom_api_base 有内容 -> 优先使用该地址\n"
        "  - custom_api_format 有内容 -> 优先使用该接口格式\n"
        "  - custom_model 有内容 -> 优先使用该模型\n"
    )

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "message": ("STRING", {
                    "default": cls.MESSAGE,
                    "multiline": True,
                }),
            },
        }

    RETURN_TYPES = ()
    FUNCTION = "show"
    CATEGORY = f"{LX_RELAY_CATEGORY}/帮助与维护"
    SIZE = (420, 360)

    def show(self, message):
        return ()
