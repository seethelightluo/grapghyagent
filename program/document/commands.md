# Slash Commands Reference

All commands are typed after the CheetahClaws prompt `[folder] » ` and start with `/`.

## Session Management

### `/help`
Show all available commands with descriptions.

### `/clear`
Clear the conversation history. The model forgets everything before this point.

### `/model [model-name]`
Show or set the model. Without arguments, lists available models by provider.

```
/model                    # list available models
/model claude-sonnet-4-6  # switch to Claude Sonnet
/model gpt-4o             # switch to GPT-4o
/model ollama             # interactive Ollama model picker
```

### `/config [key=value]`
Show or set configuration. Without arguments, shows all current config values.

```
/config                           # show all config
/config max_tokens=8192           # set max tokens
/config permission_mode=manual    # require permission for each tool
```

### `/verbose`
Toggle verbose mode. When on, shows thinking blocks and token counts per turn.

### `/thinking`
Toggle extended thinking mode (Claude models only). The model spends more time reasoning before responding.

### `/permissions [mode]`
Set the permission mode for tool calls:
- `auto` — auto-approve common tools, ask for risky ones
- `accept-all` — never ask for permission (dangerous)
- `manual` — ask before every tool call

```
/permissions auto
/permissions accept-all
/permissions manual
```

### `/cwd [path]`
Show or change the working directory. The agent operates within this directory.

```
/cwd                  # show current directory
/cwd /home/projects   # change directory
```

### `/status`
Show current session status: model, provider, token usage, cost, permission mode, active flags.

### `/doctor`
Diagnose installation health: check Python version, dependencies, API connectivity, tool availability.

### `/compact [focus]`
Manually compact conversation history to save context space. Optionally provide a focus topic to preserve relevant context.

```
/compact
/compact "task decomposition logic"
```

## Saving and Loading

### `/save [filename]`
Save the current session to a file. If no filename is given, auto-generates one with timestamp.

```
/save my-project-session
/save                    # auto-named: session_20260508_143022.json
```

### `/load [filename]`
Load a previously saved session. Restores all messagesado, token counts, and turn count.

```
/load my-project-session
```

### `/resume [filename]`
Resume the last auto-saved session (from exit) or a named file.

```
/resume                  # resume last session
/resume my-session       # resume named session
```

### `/export [file]`
Export the conversation history to a Markdown file.

```
/export summary.md
```

### `/copy`
Copy the last assistant response to the clipboard.

### `/history`
Print the full conversation history.

### `/context`
Show current context window usage (message count, estimated tokens, model max).

### `/cost`
Show estimated API cost this session (based on input/output token counts).

### `/search <query>`
Search past sessions for matching conversations.

## Checkpoint and Plan Mode

### `/checkpoint`
List or restore checkpoints. Checkpoints are auto-saved after each turn.

```
/checkpoint              # list all checkpoints
/checkpoint 5            # restore checkpoint #5
/checkpoint clear        # delete all checkpoints
```

### `/rewind [id]`
Alias for `/checkpoint <id>`. Rewinds conversation to a previous state.

### `/plan <description>`
Enter plan mode: write-protects everything except the plan file. The agent can read and plan but not modify code.

```
/plan "Add user authentication with JWT"
/plan done                # exit plan mode
/plan status              # show plan mode status
```

## Task Management

### `/tasks`
List all tasks in the task store.

### `/task create <subject>`
Quick-create a task. Opens a wizarddialog for adding details.

```
/task create "Implement user login"
```

### `/task start|done|cancel <id>`
Update task status.

```
/task start 3      # mark task 3 as in-progress
/task done 3       # mark task 3 as completed
/task cancel 3     # cancel task 3
```

### `/task delete <id>`
Delete a task from the store.

### `/task get <id>`
Show full task details including input_spec, output_spec, verification results, gate status, run logs.

### `/task clear`
Delete all tasks.

### `/task todo|in-progress|done|blocked`
Filter tasks by status.

## Skills, Memory, Agents

### `/skills`
List all available skills with their descriptions. Skills are user-invocable workflows defined in `.cheetahclaws/skills/`.

### `/memory [query]`
Show or search persistent memories. Memories are saved across sessions.

```
/memory                         # list all memories
/memory "task decomposition"    # search memories
/memory consolidate             # extract long-term insights from current session
```

### `/agents`
Show running background agents and their status.

## Plugins and MCP

### `/plugin`
List installed plugins.

### `/plugin install name@url`
Install a plugin from a URL.

### `/plugin uninstall name`
Uninstall a plugin.

### `/plugin enable|disable name`
Toggle a plugin on or off.

### `/plugin update name`
Update a plugin to the latest version.

### `/plugin recommend [context]`
Recommend plugins for the given context.

### `/mcp`
List MCP (Model Context Protocol) servers and their tools.

### `/mcp reload`
Reconnect all MCP servers.

### `/mcp add <name> <cmd> [args]`
Add a stdio MCP server.

```
/mcp add my-server python server.py
```

### `/mcp remove <name>`
Remove an MCP server from config.

## Background Agents

### `/agent`
Interactive wizard for launching autonomous agents. Guides through template selection step by step.

### `/agent start <template> [args]`
Launch an autonomous agent loop directly.

```
/agent start research_assistant ~/papers/
/agent start auto_bug_fixer --interval 5
/agent start paper_writer outline.md
/agent start auto_coder --task "add rate limiting"
```

Options:
- `--name <name>` — custom agent name
- `--interval <seconds>` — pause between iterations (default: 2)
- `--no-auto-approve` — pause for permissions

### `/agent stop <name|all>`
Stop a running agent or all agents.

### `/agent list`
List all running agents with their status.

### `/agent status <name>`
Show recent iteration log for an agent.

### `/agent templates`
List available task templates: `research_assistant`, `auto_bug_fixer`, `paper_writer`, `auto_coder`.

## Brainstorm and Worker

### `/brainstorm <topic>`
Multi-persona iterative brainstorming session. Generates 5 expert personas and runs a structured debate on the topic. Produces a master plan and TODO list.

```
/brainstorm "How to improve our CI/CD pipeline"
```

### `/worker [--path file] [--tasks N,M] [--workers N]`
Auto-implement tasks from a `todo_list.txt` file. Each task is executed in sequence.

```
/worker
/worker --path custom_tasks.txt
/worker --tasks 1, Consent3,5
/worker --workers 却2
```

## SSJ Developer Mode

### `/ssj`
SSJ Developer Mode — power menu with brainstorming, debate, worker, trading, review, and more. Opens an interactive sub-menu.

## Trading Analysis

### `/trading analyze <SYMBOL>`
Multi-agent trading analysis: Bull/Bear debate → Risk panel → PM decision.

```
/trading analyze TSLA
/trading analyze AAPL
```

### `/trading backtest <SYMBOL> [strategy]`
Backtest a strategy against historical data. Available strategies: `dual_ma`, `rsi_mean_reversion`, `bollinger_breakout`, `macd_crossover`.

```
/trading backtest TSLA dual_ma
/trading backtest AAPL rsi_mean_reversion
```

### `/trading price <SYMBOL>`
Current price and key metrics.

### `/trading indicators <SYMBOL>`
Technical indicators report: SMA, RSI, MACD, Bollinger, ADX.

### `/trading status`
Trading memory status.

### `/trading history`
Past trading decisions.

### `/trading memory [action]`
Manage trading memory: `list`, `search`, `clear`.

## Proactive and Monitor

### `/proactive [duration]`
Background sentinel polling. The agent periodically checks for events and notifies you.

```
/proactive 5m      # poll every 5 minutes
/proactive off     # disable polling
```

### `/subscribe <topic> [schedule] [--telegram] [--slack]`
Subscribe to AI-monitored topics with optional delivery channels.

```
/subscribe ai_research
/subscribe stock_TSLA daily --telegram
/subscribe crypto_BTC 6h --slack
/subscribe world_news weekly
/subscribe custom:quantum computing 12h
```

Built-in topics: `ai_research`, `world_news`, `stock_<TICKER>`, `crypto_<SYMBOL>`, `custom:<QUERY>`, `research:<QUERY>`.

### `/subscriptions` (alias: `/subs`)
List all active subscriptions.

### `/unsubscribe <topic>`
Remove a subscription.

### `/monitor run [topic]`
Run monitor(s) now and print AI report.

### `/monitor start`
Start the background scheduler daemon. Runs subscriptions on their schedules.

### `/monitor stop`
Stop the background scheduler.

### `/monitor status`
Show scheduler status and subscription overview.

### `/monitor set telegram <token> <chat_id>`
Configure Telegram delivery for monitor reports.

### `/monitor set slack <token> <channel_id>`
Configure Slack delivery for monitor reports.

### `/monitor topics`
List available built-in topics.

## Research

### `/research <query>`
Full research pipeline: searches 17 sources, generates heat table and sparklines.

```
/research transformer efficiency
/research 30d:RLHF
```

Range presets: `3d`, `7d`, `30d`, `90d`, `6m`, `1y`.

### `/reports`
View past research reports.

## Messaging Bridges

### `/telegram <bot_token> <chat_id>`
Start the Telegram bridge. The agent responds to messages sent to your Telegram bot.

```
/telegram 123:abc 456789
/telegram stop
/telegram status
```

### `/wechat login`
Authenticate WeChat (Weixin) via QR code for messaging bridge.

```
/wechat login
/wechat stop
/wechat status
```

### `/slack <token> <channel_id>`
Start Slack bridge via Web API.

```
/slack xoxb-token C01CHANNEL
/slack stop
/slack status
/slack logout
```

## Cloud Sync

### `/cloudsave setup <token>`
Configure GitHub token for cloud sync.

### `/cloudsave [push] [desc]`
Upload current session to GitHub Gist.

```
/cloudsave
/cloudsave push "after fixing auth bug"
```

### `/cloudsave auto on|off`
Toggle auto-upload on exit.

### `/cloudsave list`
List your cheetahclaws Gists.

### `/cloudsave load <gist_id>`
Download and load a session from Gist.

## Media and Voice

### `/image [prompt]`
Send clipboard image to the vision model for analysisurally. If prompt is provided, includes it with the image.

```
/image                    # just the clipboard image
/image "What does this diagram show?"
```

### `/voice`
Record voice input, transcribe it, and submit as a prompt.

### `/voice status`
Show available recording and STT backends.

### `/voice lang <code>`
Set STT language (e.g. `zh`, `en`, `ja` — default: `auto`).

### `/tts`
AI text-to-speech wizard: write a script and generate MP3 in any voice style.

### `/video [topic]`
AI video content factory: story → TTS → images → subtitles → MP4.

```
/video "History of quantum computing"
/video status
/video niches
```

## Web Server

### `/web [port] [--host H] [--no-auth]`
Start a web terminal / chat UI in background. Access the agent from a browser.

```
/web                    # start on default port
/web 8080               # start on port 8080
/web 8080 --host 0.0.0.0  # bind to all interfaces
/web status             # check if server is running
```

## Circuit Breaker

### `/circuit`
Show per-provider circuit breaker status. Providers that have failed repeatedly are auto-skipped.

### `/circuit reset <provider|all>`
Force-close a circuit breaker to recover from `circuit_open_skip` errors.

```
/circuit reset anthropic
/circuit reset all
```

## Misc

### `/init`
Initialize a `CLAUDE.md` file in the current directory with a project template.

### `/setup`
Run the interactive setup wizard to configure API keys, defaults, and preferences.

### `/exit` (alias: `/quit`)
Exit CheetahClaws. The session is auto-saved.

## Shell Escape

Any input starting with `!` is run directly in the system shell:

```
!ls -la
!git diff
!python --version
```

## Evidence Chain Skill

The `evidence_chain` skill is the primary workflow for verifiable task graph execution. See the [Evidence Chain Tutorial](evidence-chain.md) for the full 8-phase protocol.

```
/evidence_chain 搜索世界前10学校在10个学科的排名并分析误差
/evidence_chain Build a dashboard with real-time data and PDF export
```
