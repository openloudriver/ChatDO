import argparse
from .config import load_target
from .agents.main_agent import run_agent

def main():
    parser = argparse.ArgumentParser(description="ChatDO - personal repo-aware AI agent")
    parser.add_argument(
        "--target",
        required=True,
        help="Name of the target config (e.g. 'privacypay', 'drr')",
    )
    parser.add_argument(
        "--thread",
        help="Optional thread ID for persistent context (e.g. 'credit-vault', 'security-architecture')",
    )
    parser.add_argument(
        "task",
        nargs="+",
        help="Task or question for ChatDO (quoted).",
    )
    args = parser.parse_args()
    target_name = args.target
    thread_id = args.thread
    task = " ".join(args.task)
    target_cfg = load_target(target_name)
    
    print(f"[ChatDO] Target: {target_cfg.name} @ {target_cfg.path}")
    if thread_id:
        print(f"[ChatDO] Thread: {thread_id}")
    print(f"[ChatDO] Task: {task}\n")
    
    result = run_agent(target_cfg, task, thread_id=thread_id)
    print(result)

if __name__ == "__main__":
    main()

