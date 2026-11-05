请做一个可以反复设计、发射和观察轨道的三维航天沙盒。玩家能自由组合不同规格的燃料箱、发动机、指令舱、级间分离器、侧向分离器和降落伞；各部件的数据要合理，包括干质量、燃料容量、推力、比冲和降落伞适用条件。相同型号可多次安装。提供可编辑的分级列表，让玩家决定何时点火、级间或侧向分离、打开降落伞，并能调节油门和姿态。燃料耗尽后发动机停止产生推力；分离后质量、连接和推力来源应正确更新；降落伞在真空中不能产生空气阻力。世界至少包含太阳、地球和月亮，不要求真实地形或真实天文尺度，但数值单位及物理尺度须自洽。至少实现围绕一个当前中心天体的引力运动，提供轨道视图和关键轨道参数；不要求多体引力，也不强制登月。无推力真空段使用单体引力，有动力段计入推力、燃料和质量变化。让玩家能完成至少 3 种不同的有效飞行器设计，试飞失败后可回到设计或恢复存档。概念图仅作视觉参考，不要求复刻构图、轨迹或比例。物理步长固定为 20 Hz；加速时间通过多个基础步推进。默认种子为 20260914。位置和速度使用 m、m/s，质量 kg、时间 s、推力 N、比冲 s。保存和读取恢复飞行器、分离体、连接、燃料、姿态、分级和轨道状态。

使用 Blender + UE5 制作这个游戏。提交完整、可编辑、可运行的 UE5 工程，包括 .uproject、游戏关卡、资产、配置及使用到的 Blueprint、C++ 源码、插件和依赖，默认关卡应能直接启动游玩。随附简短的启动与操作说明，并标明使用的引擎版本。

## Fixed UE5 delivery contract

Submit the runnable project at `output/ue5_project/3DBenchGame.uproject`. The project root must contain `Config/` and `Content/`; `Source/`, `Plugins/`, and `SourceAssets/Blender/` are allowed when used. Put a short launch and controls note in `output/README.md`. Do not submit generated `Binaries/`, `Intermediate/`, `Saved/`, or `DerivedDataCache/` directories.

## 提供给模型的视觉参考

随输入提供 `input/reference.png` 和 `input/PROJECT_LAYOUT.md`。请参考图片中的几何风格、配色、相机构图和玩法可读性，制作风格协调的可玩三维游戏。这是生成的概念图，不是已实现游戏的截图，也不是几何 ground truth；不要求逐像素复刻、相同物体位置或相同 HUD 布局。尺寸、数量、物理、操作和流程以上面的文字要求为准，图片不会增加额外玩法要求。不能用整张图片贴在背景平面上代替可玩场景。
