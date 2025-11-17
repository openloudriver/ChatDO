import argparse
from .config import load_target
from .agents.main_agent import run_agent

def main():
    parser = argparse.ArgumentParser(prog="chatdo")
    parser.add_argument("--target", default="privacypay", help="Name of target config (e.g., privacypay, drr)")
    parser.add_argument("task", nargs="+", help="Task description for ChatDO")
    args = parser.parse_args()
    target = load_target(args.target)
    task_text = " ".join(args.task)
    print(f"[ChatDO] Target: {target.name} @ {target.path}")
    print(f"[ChatDO] Task: {task_text}\n")
    result = run_agent(target, task_text)
    print(result)

if __name__ == "__main__":
    main()

