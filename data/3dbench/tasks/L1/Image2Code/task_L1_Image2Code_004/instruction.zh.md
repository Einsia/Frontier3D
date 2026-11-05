# 老旧风力涡轮塔

根据 input/reference.png、input/front.png、input/side.png、input/top.png 重建同一物体和姿态。

按给定姿态重建旧风力涡轮塔，包括支撑框架、风轮叶片和轮毂、粗管与斜撑、底部机械和基座。保留不对称特征和清楚的间隙，不能把框架做成实心块。匹配主要锈蚀金属外观。本题只重建静态姿态，不要求源动画、发电或结构仿真。

使用真实、可编辑三维几何，保留连续曲率、厚度、凹槽、孔隙、薄构件、连接和遮挡。独立部件应为可编辑对象或清楚分离的网格岛，有机曲面可保持连续。不要求源拓扑、顶点数或对象名一致，不能用图片平面或只朝相机的薄壳代替完整实体。

使用米制、Z 向上，物体最大整体跨度为 1.000 m，容差 2%，相机与灯光不计。这是任务尺度约定，不是实物测量；其他比例从图像推断。

第 1 帧保存最终静态姿态，scene.glb 导出同一姿态。不要求动画、爆炸图或仿真。

使用匹配 input/reference.png 的相机、普通摄影棚照明、Cycles、AgX 和曝光 0，渲染 1000 × 1000 的 main.png；在 scene.blend 中保留相机和照明。

## 固定交付结构
所有交付放入 `output/`：

```text
output/
  solution.py
  scene.blend
  scene.glb
  main.png
  README.md
  assets/       # 可选的自包含辅助代码和纹理
```

在干净工作目录中重建：
`blender --background --factory-startup --python output/solution.py -- --input-dir <workspace>/input --output-dir <workspace>/output`

入口必须不依赖已有输出，生成或刷新所需场景和图像。辅助文件相对脚本定位，只读取给定输入、自行随包交付的代码/资源和已安装库。不能下载源模型、源贴图或额外参考视图，也不能将外部取得的源几何嵌入脚本。不能读取评测侧私有文件或使用个人绝对路径。纹理打包进 Blender 或使用 output/assets/ 内的可移植相对路径。在 output/README.md 说明执行方式与依赖；可选日志和附加渲染放在 output/logs/、output/renders/。

## 材质约定

仅使用纯色或程序化材质。参考图用于观察；场景、材质、灯光、几何节点及合成不得使用位图、HDRI、烘焙或生成的图像。允许 Noise、Bump 等程序化节点。
