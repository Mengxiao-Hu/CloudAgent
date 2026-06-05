"""
云端 Agent 平台 — 框架骨架(伪代码)
================================================
四个设计关注点不单独成章,而是标注在它们自然出现的位置:
  [编排] Agent 编排与调度      [沙箱] 沙箱与隔离执行
  [LLM]  LLM 集成与工具调用    [架构] 整体架构与可扩展性(接口缝)
设计依据来自对 Devin 行为的观察(见文件末尾的 trace 对照)。
"""

from typing import Protocol
from dataclasses import dataclass, field

MAX_ITERS = 50  # 全局兜底之一

# ============================================================
# [架构] 接口缝:每个"变化轴"一个接口,核心循环不依赖具体实现。
#        换模型 / 加工具 / 换隔离后端,都不动 run_agent()。
# ============================================================

class LLMProvider(Protocol):                       # 变化轴:模型
    def complete(self, messages, tool_schemas) -> "LLMResponse": ...

class Tool(Protocol):                              # 变化轴:能力
    name: str
    schema: dict                                   # 给 LLM 看的 JSON schema
    def run(self, args: dict, sbx: "Sandbox") -> "ToolResult": ...
    #                          ^ 关键:工具在沙箱里执行,不在 worker 进程里

class Sandbox(Protocol):                           # 变化轴:隔离强度
    def exec(self, cmd: str, timeout: int) -> "ExecResult": ...
    def read(self, path: str, line_range=None) -> str: ...   # 支持范围读
    def write(self, path: str, content: str): ...
    def destroy(self): ...

# ============================================================
# [沙箱] 一次性隔离环境。demo 用 Docker;生产换 Firecracker microVM
#        只需实现同一个 Sandbox 接口(这就是上面接口缝的意义)。
# ============================================================
class DockerSandbox:
    @classmethod
    def create(cls, task) -> "DockerSandbox":
        # - 一次性容器,非 root,丢弃 capabilities,seccomp
        # - 资源限额(CPU/内存/PID/磁盘):防 fork 炸弹拖垮节点
        # - 不挂载宿主目录
        # - 网络 = 默认拒绝 + 白名单(git host、PyPI/npm)
        #     ^ 编码 agent 必须能 pip install / git push,不能全禁
        # - 注入【短时效 + 仓库范围受限 + 权限位受限】的 GitHub App token
        #     ^ token 必须进沙箱(clone 在此发生),靠"做弱"而非隔离兜底
        #     ^ 注意:LLM key 不在这里!LLM 调用发生在可信 worker 里
        ...

# ============================================================
# [编排] 任务是队列里的工作单元;计划(Plan)是可持久化、可恢复的状态。
# ============================================================
@dataclass
class Step:
    desc: str
    done: bool = False

@dataclass
class Plan:                                        # 对应 Devin "Created N Tasks"
    steps: list[Step] = field(default_factory=list)
    def progress(self) -> str:                     # -> "4/12"
        return f"{sum(s.done for s in self.steps)}/{len(self.steps)}"

@dataclass
class Task:
    id: str
    tenant_id: str
    prompt: str
    policy: dict                                   # [权限] 默认拒绝的能力白名单
    status: str = "queued"
    plan: Plan = None

# ---- API 层:无状态,只做鉴权/校验/入队/读回 ----
def POST_tasks(prompt, policy_override, tenant):
    task = Task(id=new_id(), tenant_id=tenant, prompt=prompt,
                policy=resolve_policy(policy_override))
    persist(task); queue.enqueue(task.id)
    return task.id                                 # 异步:立即返回,不阻塞

# ---- [编排] Worker:无状态,从队列取任务。多开 worker = 水平扩展 ----
def worker_loop():
    while (task_id := queue.dequeue()) is not None:
        task = load(task_id); set_status(task, "running")
        sbx = DockerSandbox.create(task)           # [沙箱] 起隔离环境
        try:
            clone_repo_into(sbx, task)             # token 在沙箱内,但受限
            run_agent(task, sbx)
            set_status(task, "succeeded")
        except (Timeout, BudgetExceeded, ToolError) as e:
            set_status(task, e.terminal_status)
        finally:
            sbx.destroy()                          # [沙箱] 用完即销毁,无残留

# ============================================================
# [LLM] + [编排] 核心循环:先规划,再 observe→think→act,最后 report。
# ============================================================
def run_agent(task: Task, sbx: Sandbox):
    task.plan = planner_decompose(llm, task.prompt)  # Devin:先建 todo list
    persist(task)                                    # [编排] 计划即可恢复状态
    history = [system_prompt(), user(task.prompt)]

    for _ in range(MAX_ITERS):
        guard_budget(task)                           # 兜底:迭代/token/墙钟超时
        resp = llm.complete(history, registry.schemas())   # think

        if resp.is_final:                            # act = 回复用户
            report_to_user(task, resp.text)          # Devin 末尾的 findings
            return

        for call in resp.tool_calls:                 # act = 调工具
            check_policy(task.policy, call)          # [权限] default-deny 校验
            result = registry[call.name].run(call.args, sbx)  # 在沙箱执行
            history.append(observe(result))          # observe(含报错→下轮自我纠正)

        task.plan = sync_plan(task.plan, history)    # 更新进度 k/n
        persist(task)                                # [编排] 每步持久化→可恢复

# ============================================================
# [架构] 工具都是 Sandbox 之上的薄封装;装饰器注册只是"加工具"这条缝的实现。
# ============================================================
@registry.register
class Shell:                                        # git / gh / pip 全走这里
    schema = {...}
    def run(self, args, sbx): return sbx.exec(args["cmd"], timeout=60)

@registry.register
class ReadFile:
    def run(self, args, sbx):
        return sbx.read(args["path"], args.get("range"))  # 范围读→控制上下文

@registry.register
class WriteFile:
    def run(self, args, sbx): return sbx.write(args["path"], args["content"])

# (EditFile 同理:读区间→替换→写回,对应 Devin 的 "Edited ...+3−4")

# ============================================================
# Devin trace 对照(说明骨架的每个部分对应到可观测行为):
#   "On it. I'll clone..."        -> planner_decompose + report_to_user
#   "Created 4/10 Tasks", "4/12"  -> Plan / Step / progress()
#   "Thought for Xs"              -> llm.complete(...) 的 think
#   "cd .. && git clone"          -> Shell.run -> sbx.exec(在 /home/ubuntu)
#   "Read file.py:36-65"          -> ReadFile(range) -> 上下文控制
#   "Created/Edited test_*.py"    -> WriteFile / EditFile
#   pip install 失败→装包→重跑      -> observe 报错→下轮 think 自我纠正
#   "git push" + 开 PR            -> Shell + 受限 GitHub App token
# ============================================================
