# v2 联网研究与改进记录

本轮核对了官方工具说明与论文摘要，将可直接验证的原则用于当前 CPU 后处理模块。没有将研究论文中的模型效果数字当成本项目成绩。

## 轮廓类型、容差与尺度

Esri 的规整工具分别提供直角、斜角、任意角度与圆形处理，并把容差与原始边界的允许偏离联系起来；圆形与不同尺寸结构需要分别考虑。[Regularize Building Footprint](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/3d-analyst/regularize-building-footprint.html)

本项目据此采用形状候选与逐项保护：连续曲线先识别；直线建筑按自身方向拟合；同时限制相对墙宽位移和改动面积。这里的轮廓判断仍是启发式推断，无法恢复未知设计意图。GIS 文档的米制参数没有直接套到未标定的 PNG。

## 连续方向与共享分界

2024 年 ISPRS 的 POL 工作讨论从栅格轮廓出发，连续估计主要方向并构造规则建筑边界。[Rectilinear Building Footprint Regularization Using Deep Learning](https://isprs-annals.copernicus.org/articles/X-2-2024/217/2024/)

本版采用传统鲁棒拟合估计方向；研究检查进一步促使我们比较不同角度，发现两次栅格旋转引入的斜墙偏移。最终矩形墙线改为在原始坐标中拟合，并按原始像素中心覆盖；45° 附近的方向轴交换也做了处理。

Esri 的相邻轮廓工具强调共享边界应共同规整，并在无法得到有效方案时保留原特征。[Regularize Adjacent Building Footprint](https://doc.esri.com/en/arcgis-pro/latest/tool-reference/3d-analyst/regularize-adjacent-building-footprint.html)

本版对两个稳定色区的共同直线分界只拟合一次，联合重分配两侧标签，保持同一前景覆盖。相应回归测试发现并修复了“在移动后的界线上重新检测原始色差，误把真分区标成弱梯度”的顺序问题。证据判断现于改动前进行。

## 用边界指标检查边界改进

Boundary IoU 的研究表明，普通 Mask IoU 对大目标的局部边缘问题可能不够敏感；边界指标可补充该信息。[CVPR 2021: Boundary IoU](https://openaccess.thecvf.com/content/CVPR2021/html/Cheng_Boundary_IoU_Improving_Object-Centric_Image_Segmentation_Evaluation_CVPR_2021_paper.html)

新增 15 组已知矩形真值的角度/尺度实验，同时计算掩膜 IoU 和内部边界带 IoU。边界带使用 3×3 腐蚀构造，宽度按实验尺度为 1、2、3 像素。这是本项目明确配置的几何测试，不是复现论文完整实例评估协议。

该检查实际发现了斜墙偏移，并推动了坐标拟合修复。最终 11 组指标提升、4 组画面截断样例保守回退；全部逐例值保存在 `validation_v2/synthetic_boundary_metrics.csv`。对于没有真值的用户 PNG，仅记录改动、连通区域与复核情况，不报告“准确率”。

## 进一步研究的适用方向

BuildMapper 将建筑表达为可学习的矢量轮廓，包含轮廓初始化、演化与角点相关预测。[BuildMapper](https://arxiv.org/abs/2211.03373)

结合本项目现状，我的判断是：如果后续主要残差变成大范围结构错误，应优先积累少量人工确认的 footprint 与高度分区标签，用于评价或训练结构化轮廓模块。仅加大形态学修补半径容易误删小塔楼、浅入口和曲线。当前先保留独立 CV 模块、清晰的复核掩膜与可选权威前景输入，方便之后接入标注或结构化输出。
