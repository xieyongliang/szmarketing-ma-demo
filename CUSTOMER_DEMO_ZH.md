# 使用 ModelArk Managed Agents 完成 POD 素材生成与评测闭环

[English](CUSTOMER_DEMO_EN.md)

本文介绍 SZ Creative Studio 的部署与复现方法：通过 ArkCLI 部署 MA、Cloud Environment 和 Skill，再通过网页提交需求，由 MA 在云端生成图片与视频、独立评测、审计，并按需改进。

**实测基线：2026-09-26，Agent / Skill v9。** 本次真实云端运行首轮模型评分 **5/5**，所有必需项通过，状态为 `completed`，立即返回第 1 轮。配置为最多 3 轮、目标 4.5/5、水印关闭。不保证复现相同素材或分数。

模型验收不等于人工视觉、印刷、版权或广告平台发布批准。本文需与源码一起交付，验证边界见第 9 节。

## 1. Demo 可以完成什么

- 根据需求形成创意方向和提示词；Skill 要求公开信息检索，但本次实测未验证研究能力。
- 使用 Seedream 生成一张图案和一张商品场景图。
- 使用 Seedance 生成一段 5 秒、9:16 的商品展示视频，默认不生成音频。
- 由模型直接查看实际图片和视频，依据动态验收清单评分。
- 复核评测结论与证据的一致性，有冲突时进行额外裁决。
- 按最高优先级缺陷修改提示词，继续生成和评测，直到达标或达到轮次上限。
- 在网页查看素材、评分、验收项和历史版本，导出 Campaign JSON。

当前默认最多 3 轮，目标分数 4.5/5，可在创建 Campaign 时调整；最多允许 5 轮。每轮是一组素材，不是多个并行候选。模型判断不等于印刷生产批准、版权许可或广告平台审核通过，最终发布仍需人工确认。

## 2. 架构与职责

```text
用户浏览器
  -> 本地 Node.js 服务：创建 Session、提交需求、观察事件、展示结果
      -> MA Cloud Session
          -> MA 主模型：检索、拆解需求、生成提示词、决定修改方向
          -> pod-creative-loop Skill + Python 脚本
              -> Seedream：图案与场景图
              -> Seedance：提交视频任务与查询结果
              -> /responses：独立评测上下文，查看实际素材
              -> /responses：一致性审计上下文，核查评测证据
              -> /responses：仅发生冲突时调用裁决上下文
          -> 主模型根据反馈修改提示词，继续下一轮
          -> 导出经过校验的结果，返回本地页面
```

云端 Campaign 的生成与评测 API 调用在 MA Cloud 内发生。本地服务负责 Session 交互和展示，不承担该 Campaign 的生成编排。执行期间建议保持本地服务运行，以持续接收和保存结果。

评测、审计和裁决使用独立模型请求上下文，可以使用同一个模型；不是三个额外部署的 MA Agent。评测上下文不接收创作者的推理过程或自评分，但会收到原始需求、验收标准和实际素材。审计与裁决还会收到待核查的报告。

无需额外部署 MCP Server，也不需要向 MA 开放本地公网入口。Cloud Environment 需要能够向外访问模型 API 和素材 URL。

## 3. 准备条件

1. 已开通 Managed Agents 和所需模型权限的 BytePlus 账号，具备相关资源操作权限。
2. 已安装并可正常登录的 BytePlus ArkCLI，而非其他租户版本。
3. Node.js 22 或更高版本、npm、Python 3、zip。
4. 可用于本次 Demo 的专用模型 API Key，以及创建专用 Cloud Environment 的权限。
5. 本 Demo 的源码目录。本文不是独立运行包，需要与代码一起交付。

需要的主要文件：

```text
szmarketing-ma-demo/
  package.json
  package-lock.json
  .env.example
  server.mjs
  cloud.mjs
  core.mjs
  cloud-system.md
  deploy-environment.mjs
  public/
  skills/pod-creative-loop/
    SKILL.md
    scripts/creative.py
    scripts/evaluation.py
  test.mjs
  test-cloud.py
```

不要将原测试环境的 `.env`、`data/`、认证目录或带签名的私有素材链接一起发送给客户。

本实现的默认模型如下，实际可用性以客户账号为准：

| 用途 | 默认模型 |
| --- | --- |
| MA 主模型（本次部署） | `seed-2-0-lite-260428` |
| 图片生成 | `seedream-4-5-251128` |
| 视频生成 | `dreamina-seedance-2-5-260628` |
| 评测、审计与裁决 | `seed-2-0-lite-260428` |

云端脚本从 Cloud Environment 读取 `IMAGE_MODEL`、`VIDEO_MODEL`、`EVAL_MODEL`，其中评测模型也支持 `VISION_MODEL` 回退。只修改本地 `.env` 的模型名称，不会修改云端脚本使用的模型。更换模型还需确认其接口及输入参数兼容。

## 4. 部署 MA Cloud

以下命令从源码根目录执行，使用客户自己的账号、Key 和资源 ID。命令中的占位符需替换为实际返回值。资源创建、模型调用及运行环境可能产生费用。

### 4.1 登录并确认账号

```bash
arkcli --version
arkcli auth login
arkcli auth status --format json
arkcli profile show --format json
```

确认当前租户为 BytePlus、目标 Region 为 `ap-southeast-1`，且账号和项目正确。不要把完整认证输出、Key 或环境配置粘贴到公共渠道。

### 4.2 打包并上传 Skill

```bash
mkdir -p data
cd skills
zip -r ../data/pod-creative-loop.zip pod-creative-loop -x '*/__pycache__/*'
cd ..
arkcli agent skill create --zip data/pod-creative-loop.zip --display-title 'SZ Autonomous POD Loop' --format json
```

记录返回的 Skill ID 和版本。ZIP 必须包含顶层 `pod-creative-loop/` 目录，以及 `SKILL.md`、`creative.py`、`evaluation.py`，不要加入任何凭据。

更新已有 Skill 时使用 `arkcli agent skill update <SKILL_ID> --zip data/pod-creative-loop.zip --format json`，再将 Agent 绑定到返回的新版本。旧 Session 不会自动切换到新 Skill，应创建新 Campaign / Session。

### 4.3 创建专用 Cloud Environment

本 Demo 使用 Environment 的 `Config.Env` 注入 API Key。它不是专用密钥库；能读取环境配置或在环境中执行代码的人可能访问 Key。仅在获得授权后使用专用测试 Key，勿与其他不受信任任务共享环境。

如需修改环境名称，可先修改 `deploy-environment.mjs` 中的 Demo 名称。下面使用 Bash 隐藏输入，避免把 Key 写入命令历史：

```bash
read -r -s -p 'BytePlus demo API key: ' ARK_API_KEY
printf '\n'
export ARK_API_KEY
node deploy-environment.mjs
unset ARK_API_KEY
```

脚本创建 Cloud Environment，配置出站网络和 `ARK_API_KEY`，只输出环境 ID，不输出 Key；临时配置文件用后删除。记录 `environment_id`。

如果命令超时或提示未确认创建，先在控制台检查资源是否已创建，不要盲目重复执行。不要为了排错直接打印整个 Environment 或 Session 配置，其中可能包含凭据。

### 4.4 创建 Agent 并绑定 Skill

先确认所选主模型位于当前账号的 MA 可用模型列表：

```bash
arkcli agent model list --format json
```

使用上一步上传的 Skill ID 和版本创建 Agent：

```bash
arkcli agent agent create \
  --name 'sz-pod-creative-demo' \
  --model '<AVAILABLE_MA_MODEL_ID>' \
  --system @cloud-system.md \
  --skill '{"SkillId":"<SKILL_ID>","Version":"<SKILL_VERSION>"}' \
  --format json
```

保留默认工具集，让 MA 能读取 Skill、执行脚本和检索资料。记录返回的 Agent ID，并检查 Skill 绑定：

```bash
arkcli agent agent get <AGENT_ID> --format json --transform 'Result.Skills'
```

## 5. 启动前端与本地服务

```bash
npm ci
cp .env.example .env
```

编辑 `.env`，填入客户自己创建的资源 ID：

```dotenv
PORT=8790
CLOUD_AGENT_ID=<AGENT_ID>
CLOUD_ENVIRONMENT_ID=<ENVIRONMENT_ID>
MA_AGENT_ID=<AGENT_ID>
MA_ENVIRONMENT_ID=<ENVIRONMENT_ID>
ENABLE_PAID_RUNS=true
```

`CLOUD_*` 用于新建的云端 Campaign；当前页面连接状态还读取 `MA_*`，因此此 Demo 中两组可填写相同资源 ID。本地 `ARK_API_KEY` 可以留空，由已认证的 ArkCLI Profile 提供 Session 访问凭据。云端 API Key 则已在专用 Environment 中单独配置。

```bash
npm test
python3 test-cloud.py
npm start
```

打开 http://127.0.0.1:8790/ 。若端口被占用，修改 `PORT` 后重新启动并访问对应端口。该服务只监听本机，不是带认证、多租户隔离的生产服务。

## 6. 创建一次完整测试

`watermark` 是客户可选参数：勾选 **AI-generated watermark** 传入 `true`，取消勾选传入 `false`，同时应用于图片与视频。默认勾选；本例应取消勾选以匹配不允许额外文字的需求。参数初始化后固定，修改需要新建任务。删除参数不等于关闭水印，也不能用提示词覆盖它。

点击 **New campaign**，填写：

| 字段 | 示例 |
| --- | --- |
| Campaign name | Personalized botanical mug |
| Product | Mug |
| Platform | TikTok |
| Audience | US gift shoppers, ages 25–44 |
| Maximum rounds | 3 |
| Quality target / 5 | 4.5 |
| AI-generated watermark | 取消勾选（false） |

在 Creative brief 中填写以下需求：

```text
Create an original personalized ceramic mug gift with a simple blue botanical
line drawing and the exact large text ALEX. Deliver isolated flat print artwork
on a plain white canvas, a lifestyle mockup with the print facing the camera,
and a silent 5-second vertical product showcase. Keep the exact artwork and
ALEX lettering readable and consistent across all assets. No extra text,
trademarks, music, invented claims or customer testimonials.
```

点击 **Create campaign** 保存需求，再点击一次 **Run cloud loop** 启动。创建需求记录本身不触发生成；启动云端闭环后会产生调用和运行费用。

页面显示 Session ID 和已观察到的云端事件数量。最终素材和评测主要在 MA 导出完整结果后呈现，不应因尚未看到图片而重复启动。

MA 应按以下顺序执行：

1. 检索相关公开资料，记录来源；没有可靠来源时明确说明，不能声称已验证畅销数据。
2. 从 brief 生成动态验收清单，记录每项标准对应的用户要求、必需性、优先级、权重和适用素材。
3. 初始化并固定需求与验收标准，然后生成图案、场景图和视频。
4. 独立评测模型查看实际素材，给出逐项状态、分数、证据和改进建议。
5. 审计模型检查结论与证据是否矛盾，以及清单是否漏掉原始要求；有冲突时再调用裁决模型。
6. 未达标且仍有轮次时，由 MA 修改提示词并生成下一轮；不允许降低标准来获得通过。
7. 导出最佳已评测轮次及完整报告，网页展示结果。

首轮可能直接达标，也可能多轮后仍不达标。一次首轮达标的真实运行只能验证直通流程，不能证明真实改进分支已执行；确认改进需检查报告中确实存在多轮及对应修改。

## 7. 如何判断是否成功

### 7.1 分开判断执行完成与质量通过

返回策略：某轮必需项全部通过且达到分数阈值，立即返回该轮；达到上限时，优先从必需项全部通过的轮次中选最高分，只有不存在这类轮次时才从全部轮次中选最高分。同分保留较早轮次。返回所选轮次的素材、失败项、未验证项和分数差距；“最佳可用结果”不表示达到目标。

| 状态 | 含义 |
| --- | --- |
| `completed` | 所有必需项通过、无未解决的清单覆盖缺口，且达到目标分数 |
| `needs_revision` | 需改进，MA 应继续修改提示词 |
| `max_rounds` | 达到轮次上限，停止生成；不表示质量通过 |
| `blocked` | 验收清单遗漏需求，需修正需求拆解并新建 Campaign，不能悄悄修改已固定标准 |
| 执行错误 | API、认证、响应格式等问题，不能视为评测通过 |

总分由脚本按固定权重计算：`sum(score × weight) / sum(weight)`。模型不能自行覆盖总分。非必需偏好未满足可影响分数，但不单独阻止必需项通过；必需项 `fail` 或 `unverified` 则不能完成验收。未解决的冲突不能作为必需项通过的依据。

### 7.2 在页面检查

- **Print design**：打开图案，核对是否为需求要求的交付物。
- **Mockup**：核对商品和图案呈现是否一致。
- **Video**：播放完整视频，核对时长、文字、动作和音频要求。
- **Acceptance criteria**：检查动态标准是否覆盖原始需求，是否错误降低必需性。
- **Review**：检查逐项证据、分数、必需项状态、最高优先级改进项，以及审计或裁决标记。
- **Previous versions**：有多轮时，比较实际素材与报告，不只比较总分。

独立上下文和审计降低自评偏差，但无法保证模型不误判。针对高风险要求仍需要人工抽查。音频未被可靠观察时，不应仅凭请求中设置静音就推断成品已满足音频要求。

### 7.3 保存复现证据

记录 Campaign ID、Session ID、Agent / Skill 版本、模型名称、原始 brief、轮次上限与阈值。导出 JSON 后，检查 `cloud.result` 中的 `criteria`、`rounds`、`best_round`、`status`、`return_policy`、`result_summary`，以及每轮的 `evaluation`、`audit` 和可选 `adjudication`。

导出按钮生成 Campaign JSON，不会把远程图片和视频打包。应在签名 URL 有效期内另行保存素材。访问素材时保留完整签名参数，过期链接不能通过删除参数恢复。

如果浏览器未完成 JSON 下载，可在服务端保存相同 Campaign 数据。将下方 ID 替换为页面对应 Campaign ID，在 Bash 执行：

```bash
CAMPAIGN_ID='<CAMPAIGN_ID>' node --input-type=module -e '
import {readFileSync,writeFileSync} from "node:fs";
const job=JSON.parse(readFileSync("data/jobs.json","utf8"))[process.env.CAMPAIGN_ID];
if(!job) throw Error("Campaign not found");
writeFileSync("campaign-export.json",JSON.stringify(job,null,2),{mode:0o600});
'
```

导出内容可能包含客户需求、Session ID 和签名素材链接，分享前检查并脱敏。

## 8. 重试与异常处理

| 情况 | 行为与处理 |
| --- | --- |
| Seedance 任务明确返回已识别的临时服务错误 | 每轮最多创建两个替代任务，使用已有图片，采用 5/10 秒退避；可能额外计费 |
| 查询视频任务时网络失败、429 或 5xx | 同一任务 ID 有限重试，不重复创建视频 |
| 视频创建请求结果不确定 | 不自动重提，先确认原任务，避免重复生成与计费 |
| 内容策略、未知错误、任务过期或取消 | 停止并检查原因，不无限重试 |
| 视频观察超过 30 分钟 | 停止观察，不代表远端任务已取消 |
| `/responses` 返回 HTTP 200 | 还需收到 `response.completed` 且状态为 `completed`，并通过报告格式校验 |
| SSE 提前断开、`response.incomplete` 或无效 JSON | 不能记为成功；每个评测、审计、裁决阶段最多两次尝试 |
| 本地观察中断或服务重启 | 使用 **Resume observation** 观察原 Session，不重复提交原 brief；若云端本身已报错则需另行诊断 |
| 登录过期 | 重新运行 `arkcli auth login`，确认状态后恢复观察 |
| 状态签名校验失败 | 不手动改 `state.json` 或伪造评分，保留记录并排查 |

质量轮次和 API 重试是不同限制。最多 3 轮不代表只有 3 次 API 调用，也不构成固定费用上限。

## 9. v9 真实测试结果

### 9.1 配置与执行

| 项目 | 实测值 |
| --- | --- |
| Agent / Skill | v9 / v9（测试账号内版本号，新账号使用上传返回的版本） |
| 商品 / 渠道 | Mug / TikTok |
| 最大轮次 / 目标 | 3 / 4.5 分 |
| 水印 | false，导出与客户请求一致 |
| 动态验收项 | 5 项：4 项必需、1 项偏好 |
| 实际轮次 | 1 |
| 输出 | 1 张图案、1 张场景图、1 段视频 |
| 评测流程 | 独立评测与一致性审计 |
| 审计冲突 | 无，未调用裁决 |
| 状态 / 返回轮次 / 分数 | completed / 第 1 轮 / 5 分 |
| 事件数 | 62 |

以下是模型报告中的判断，不是另一次人工检查：

| 验收项 | 类型 | 权重 | 状态 / 分数 |
| --- | --- | --- | --- |
| 白底独立图案、蓝色植物线稿与 ALEX 文字 | 必需 | 3 | pass / 5 |
| 商品场景图与图案一致，印刷面朝镜头 | 必需 | 3 | pass / 5 |
| 静音、5 秒、9:16 视频及图案一致性 | 必需 | 3 | pass / 5 |
| 无额外文字、商标、虚构声明等内容 | 必需 | 2 | pass / 5 |
| 礼品风格与目标受众匹配 | 偏好 | 1 | pass / 5 |

### 9.2 实际返回摘要

完整素材链接及证据在导出 JSON 中。以下摘录真实 `result_summary`，不含私有资源 ID、Key 或签名链接：

```json
{
  "selected_round": 1,
  "score": 5,
  "stop_reason": "completed",
  "met_target": true,
  "score_gap": 0,
  "failed_checks": [],
  "unverified_checks": [],
  "uncovered_requirements": []
}
```

返回策略为 `required_pass_then_score_or_early_pass`。本次未生成第 2、3 轮。达到上限的任务会返回按优先级选出的轮次及其失败项，而不是混合所有历史轮次的问题。必需项通过但分数不足时，失败数组可能为空，仍需查看 `met_target` 和 `score_gap`。

### 9.3 验证边界

- 已验证：真实云端生成、独立评测、审计、首轮达标提前停止、成功导出和后端校验；水印参数为 false。
- 本次未触发：后续改进轮次、冲突裁决、达到上限后的择优分支。不能把这些分支都算作本次实测。
- 本地测试：55 项（26 项 Node.js、29 项 Python），包括必需项通过优先、无通过轮次时按最高分回退、同分保留较早轮次和提前通过。模拟模型测试不证明真实素材质量。
- 本次导出 `research=[]`，不能声称已完成市场调研、竞品销量或实时趋势分析。
- 本次未追加验证人工逐张/逐帧检查、独立视频元数据、浏览器媒体播放及下载、印刷规范、版权或平台批准。此前浏览器预览和下载问题不能因模型得分 5 分而视为已解决。
- 模型与动态标准仍可能误判或产生歧义，尤其独立图案与杯子商品图的区别，应检查实际素材，不能只看分数。
- 请求参数不是素材事实。关闭可选水印不意味着移除溯源信息或免除发布标识要求。

初始消息提交曾在本地超时，但云端已接收。恢复观察时，后端核对已有消息与 Campaign 的需求及参数匹配后继续读取，没有重发任务。不要仅因页面显示超时而重复生成。

## 10. 演示与生产边界

该 Demo 是素材生成与评测原型，不包含自动投放、实时竞品销量接口、工厂印刷交付或自动发布。连接器固定为两张图片与一段 5 秒竖屏视频；动态验收不代表任意交付类型均已实现。

可对客户描述：“MA 在云端完成素材生成与模型评测，本次首轮模型验收通过并提前停止。未达标时可自动改进，达到上限按必需项通过优先返回最佳可用结果，并列出剩余问题。”不要承诺每次都能得到 5 分或直接发布。

生产落地还需访问控制、合适的密钥管理、素材持久化、成本控制、观测与人工审批。分享源码时排除私有 `.env`、`data/`、认证缓存和签名链接；客户使用自己的资源。
