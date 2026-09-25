# PDF → Word 转换说明（本机实测三种路径）

题目论文的公式很重，因此"PDF 转 Word"的关键指标是**公式形态**。
本机实测了三条路径，结论先行：

| 路径 | 命令/脚本 | 公式形态 | 可编辑 | 耗时 | 页数 |
|---|---|---|---|---|---|
| **① Word 自带 PDF 重排（分块）** | `scripts/diag/pdf_to_docx_chunked.py` | **图片**（内联图） | ❌ | ~8 min | 71 |
| ② pdf2docx（纯 Python） | `scripts/diag/pdf_to_docx.py --method pdf2docx` | 文本/图片 | ❌ | 36 s | — |
| **③ pandoc 从 LaTeX 源** | `scripts/build_word_from_latex.ps1` | **554 个原生 OMML** | ✅ | 秒级 | 75 |

## 关键结论

**从 PDF 转出来的 Word，公式一定是图片** —— PDF 里的公式已是矢量字形，
丢失了语义结构，任何工具都无法还原成可编辑公式对象。
实测 Word 重排产出 `m:oMath = 0`、内联图 83 个；pdf2docx 同样为 0。

**要"可双击编辑的原生公式"，只能从 LaTeX 源转**（③，即 pandoc 路线）。

①与③的取舍：
- ① 保留 PDF 的**公式编号 (8)(9)(10)** 与原始版面，适合"要一份和 PDF 长得一样的 Word"；
- ③ 公式**原生可编辑**、共 554 个（行内也转），但版面由 Word 重排，无公式编号。

## 三条路径的踩坑记录

1. **Word COM 不继承进程 cwd**：传相对路径会被解析到 `C:\Windows\system32`，
   报「很抱歉，找不到您的文件」。**必须 `.resolve()` 成绝对路径**。
2. **整本 56 页一次性重排会崩**（`RPC 服务器不可用`），且极慢（3 页 274 s，
   含 Word 冷启动）。**按 4 页切片后单片仅 ~15 s，全量 ~8 min**，稳定成功。
3. **切片进行中不要清理切片目录**：Word 会卡死在模态对话框上
   （表现为 WINWORD 进程 CPU 停在个位数、任务永不返回）。
4. `gencache` 缓存损坏会报 RPC 不可用；清掉
   `%LOCALAPPDATA%\Temp\gen_py` 并改回 `win32.Dispatch` 可恢复。
5. pandoc 路径另有一坑：**必须在 `otheragent/` 下运行**，否则
   `\input{texfile/...}` 全部静默丢失（只出封面 2 页，退出码仍为 0）。
