# 可动上翻柜门铰链与伸缩撑杆

根据 input/reference.png、input/front.png、input/side.png、input/top.png 重建同一物体和姿态。

重建带上翻框门的壁柜、两侧上部铰链和两根带转动接头的伸缩撑杆。保留柜腔、薄板、门框与半透明门芯。门绕顶部铰链轴旋转；撑杆在柜体和门的连接点转动，并沿自身轴向伸缩、保持连接。不能用整门平移或拉伸刚性零件伪造开门。不要求气压或弹簧力仿真。

使用真实、可编辑三维几何，保留连续曲率、厚度、凹槽、孔隙、薄构件、连接和遮挡。独立部件应为可编辑对象或清楚分离的网格岛，有机曲面可保持连续。不要求源拓扑、顶点数或对象名一致，不能用图片平面或只朝相机的薄壳代替完整实体。

使用米制、Z 向上，物体最大整体跨度为 1.000 m，容差 2%，相机与灯光不计。这是任务尺度约定，不是实物测量；其他比例从图像推断。

四张主参考图展示开门姿态。input/closed.png 与 input/half_open.png 采用同一主相机展示闭合与中间姿态。按 input/motion.json 设置 24 fps：第 1 帧闭合、31 帧半开、61 帧打开、91 帧半合、121 帧再次闭合。连续完成开合循环，匹配可见姿态、连接关系和旋转方向，不要求复制源动画的精确缓动。1 m 跨度在第 1 帧测量；刚性部件形状和尺度保持不变。Blender 保存于第 61 帧便于查看，Blender 与 GLB 均保留 1–121 帧动画；main.png 渲染第 61 帧。不要求爆炸图。

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
