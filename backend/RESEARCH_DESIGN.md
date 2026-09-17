# 设计与工程取舍

## 截图诊断

用户 2026-09-09 的三张截图显示：开场城市已形成紫黑哑光风格；工作台的左侧说明过重、聊天空白过大；后端返回 502 时，“规划引擎”仍呈绿色等待状态；地图黑屏且资源图标缺失。

本轮保留已验证的开场场景，把改造重心放在完整工作流：规划生成、已有图片后处理、方案归档，以及可恢复的任务状态。

## 官方参考与本项目的应用

1. [ArcGIS Urban 产品概览](https://www.esri.com/en-us/arcgis/products/arcgis-urban/overview)：以方案与三维分析组织规划工作。本项目采用明确的方案库及二维/三维/分析视图，不虚构 GIS 指标。
2. [ArcGIS Urban 分析说明](https://doc.esri.com/en/arcgis-urban/latest/get-started/get-started-analysis.html)：强调度量对于方案判断的作用。本项目展示真实图像质量报告；代理日照、通风指标和真实物理量分开表达。
3. [Forma 方案分析对比教程](https://www.autodesk.com/learn/ondemand/tutorial/compare-analysis-with-forma)：为设计检查提供明确的对比入口。本项目将原图与后处理结果的分割对比、复核掩膜纳入方案查看器。尚未实现两个独立规划方案的指标对比。
4. [FastAPI 同步与异步说明](https://fastapi.tiangolo.com/async/)：耗时同步操作不应直接放在事件循环中。本项目增加单线程任务队列与状态查询，原同步操作型路由使用同步函数，由框架线程池调度。
5. [Cesium Viewer](https://cesium.com/learn/cesiumjs/ref-doc/Viewer.html)、[静态资源复制插件](https://github.com/sapphi-red/vite-plugin-static-copy)：设置明确底图、处理资源错误；按实际安装插件的目录保留规则修正 `stripBase`，验证 Assets、Widgets 路径。

这些参考用于确定信息结构和工作方式；界面组件、说明插图及样式由本项目代码实现，没有复制第三方产品截图或素材。

## 视觉原则

保留紫色品牌，把工作台收敛为深墨色表面、低饱和紫色操作强调和白底规划图。减少大段重复介绍，把中心画布交给方案本身。桌面分为导航、研究侧栏、画布、规划助手；窄屏改为可滚动的纵向工作流，关键入口仍可访问。

## 功能边界

- 使用现有图片可完成 CPU 后处理、三维示意与代理分析，不需要 GPU 模型。
- 不对未配置的模型显示“可生成”；演示模式明确标注。
- 不把连通分量当成建筑栋数，不依据亮度推断真实楼高。
- 地图边界当前用于记录研究范围，未作为生成约束。
- 本轮不是账号系统或云端推理部署；原本地生成路径保留。
