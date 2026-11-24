# Book to Tutor

一个配合 Obsidian 使用的中文读书教学 skill。把技术教材 PDF 交给 agent，它会按节读完整本、生成带出处的笔记，并把新内容融入库里已有的概念。之后可以从任意一章提问，看完图解或本地动画，再把自己的理解讲给导师听。

## 开始使用

1. 把本仓库中的 [book-to-tutor](book-to-tutor/) 整个文件夹复制到你的 agent 能发现 skill 的目录。例如，Codex 可将它安装在个人技能目录中，形成 `~/.codex/skills/book-to-tutor/SKILL.md`。保留 scripts、references 和 assets。
2. 让 agent 使用带 PyMuPDF 的 Python 3.9 或更新版本。在本仓库根目录可执行：

   ```sh
   python -m pip install -r book-to-tutor/requirements.txt
   ```

3. 在能够读取本地文件的 agent 中选择这个 skill，给它 PDF，例如：

   > 用 $book-to-tutor 把这本书完整读入我的 Obsidian 库。先问我库的位置。完成后给我全书入口。

4. 导入后可以直接问「这段代码为什么需要两次同步？给我能点开的原书和演示」。想自己讲时说「我来讲讲」。[打开原创分块矩阵乘法演示的文件](book-to-tutor/assets/tiled-matmul.html) 下载到本地后可以直接用浏览器播放。

每节中文笔记回答六问：生产现场遇到了什么问题、本节解决哪一部分、机制怎样运作、哪些条件重要、哪个例子能说明它，以及回到同一现场可以交付什么、如何验证。原书、导师推断、外部资料和读者心得各有归属。

## 数据和进度

书籍首页与笔记在读者选择的 vault 中。登记工具按 PDF 内容辨认同一本书，支持从未完成的页继续；章节讲解、图文核对和逐节问答由运行 skill 的 agent 完成。更新共用概念时保留读者原文和手工修改。首次选择的库路径保存在本机用户配置中。

第一版以 PDF 为输入。文字、公式和图片都需要结合版面检查。扫描质量或当前 agent 的图像能力不足时，导入结果列出具体缺口。可从 [技能入口](book-to-tutor/SKILL.md) 查看完整工作流。
