# RocketSim: 2D 空射 vs 地射弹道导弹仿真

受 RocketPy 设计思想启发的 2D 垂直大圆平面点质量弹道仿真。目标: 同技术包线
(同推进剂/同 Isp/同干重) 下, 亚音速轰炸机空射 (ALBM) 与地面垂直发射 (GLBM)
在 "命中速度 >= Vmin" 约束下的最大有效射程对比与机理分析。

设计定稿与决策记录见 `PLAN.md` (单一事实来源)。报告与图产出见 `output/`。

## 环境

- conda 环境 `myenv` (python 3.14, conda-forge + defaults, Freeside 规范);
  `~/anaconda3/bin/conda`。缺失依赖 (scipy/matplotlib/mypy) 已装入 myenv,
  Freeside `env/environment.yml` 同步待用户操作 (`sync_env_push.sh`)。
- 运行目录: 本目录 (`RocketSim/`), 所有命令在其下执行。

## 测试与静态检查

```bash
~/anaconda3/envs/myenv/bin/python -m pytest -q        # 53 用例
~/anaconda3/envs/myenv/bin/python -m mypy missile_sim tests
```

## 手动运行接口 (CLI)

统一入口 `python -m missile_sim.cli`:

| 命令 | 内容 | 耗时 |
| --- | --- | --- |
| `--scenario final` | 纯弹道 vs 升力滑翔 (v1) 双场景最终图与报告 -> `output/lift_v1/` | ~8-12 min |
| `--scenario ballistic` | 纯弹道场景最优表格 | ~3-5 min |
| `--scenario lift` | 升力滑翔 v1 场景最优表格 (分段法向过载指令) | ~4-6 min |
| `--quick` | 追加: 小搜索预算快速冒烟 (popsize=5, maxiter=8) | ~1-2 min |

常用调参: `--vmin 700 --seed 20250905 --popsize 12 --maxiter 25 --outdir output`。
旧接口保留: `python -m missile_sim.report` 生成 M4 纯弹道报告到 `output/`。

最终报告产物 (`output/lift_v1/`): `report.md` + `fig_front.png` (样本前端与
两模式最优点) + `fig_trajectories.png` (滑翔实线 vs 弹道虚线) +
`fig_appendix.png` (Mach/q/Cd/大气剖面)。

## 输出与复现

- 全部结果由种子固定可复现; 参数为量级占位值, 不映射任何真实型号;
- 核心结论 (v3 定稿 + M1-M4): ALBM 最大有效射程 ~1103 km vs GLBM ~733 km
  (纯弹道), 空射增益约 +50%; 升力滑翔 (PLAN 11b, v1/v2) 机制已验证但兑换率
  低 (~+1%), 受细长轴对称体 L/D ~1.5 与 Vmin 地板限制, 结论见 PLAN 11b。
