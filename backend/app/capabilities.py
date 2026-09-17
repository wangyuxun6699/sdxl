"""Report configuration truthfully; configured is not a successful GPU probe."""
from pathlib import Path
import os
from .settings import is_test_mode


def capabilities():
    test = is_test_mode()
    model = os.getenv('SDXL_BASE_MODEL_PATH', '').strip()
    local = bool(model and Path(model).exists())
    return {
        'status': 'ok', 'api_version': '3.0.0',
        'postprocessing': {'available': True, 'version': '2.0.0', 'palette_required': False},
        'generation': {
            'mode': 'demo' if test else ('local' if local else 'unconfigured'),
            'configured': test or local,
            'message': '演示模式：生图使用示意块体，后处理与分析真实执行' if test else (
                '本地模型路径已配置，尚未验证推理状态' if local else '生成模型尚未配置，可直接上传已有规划图'),
        },
        'uploads': {'formats': ['png'], 'max_bytes': 12 * 1024 * 1024, 'max_pixels': 4_194_304},
        'analysis': {'kind': 'schematic_proxy', 'message': '未标定真实高度与尺度时，仅用于形态研究'},
    }
