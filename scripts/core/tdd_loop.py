#!/usr/bin/env python3
"""
TDD Loop Orchestrator (Test-Driven Development)
Automates the TDD cycle:
1. Writes test stub
2. Runs test (expects failure)
3. Stubs implementation
4. Prompts agent (simulated here for framework) to fix it.
"""
import sys, os, subprocess, time

def run_tdd(goal: str):
    print(f"🚀 Starting TDD Loop for goal: '{goal}'")
    print("--------------------------------------------------")
    
    # Define files
    test_file = "test_feature.py"
    impl_file = "feature.py"
    
    # 1. Write initial test (mocked for the orchestrator)
    print(f"Step 1: Generating Test case -> {test_file}")
    with open(test_file, "w") as f:
        f.write(f"""import pytest
from feature import run_feature

def test_goal():
    # Goal: {goal}
    result = run_feature()
    assert result is not None
    assert result == "SUCCESS"
""")
    time.sleep(1)

    # 2. Write implementation stub
    print(f"Step 2: Generating Implementation stub -> {impl_file}")
    with open(impl_file, "w") as f:
        f.write(f"""def run_feature():
    # TODO: Implement {goal}
    return None
""")
    time.sleep(1)

    # 3. First Test Run (Should Fail)
    print("Step 3: Initial Test Run (Expecting Failure)...")
    res = subprocess.run(["pytest", test_file], capture_output=True, text=True)
    if res.returncode != 0:
        print("✅ Test failed successfully! Proceeding to implementation.")
    else:
        print("❌ Test passed unexpectedly. Aborting.")
        return

    time.sleep(1)
    # 4. Implementing solution (Mocking agent fix)
    print("Step 4: AI Agent writing implementation...")
    with open(impl_file, "w") as f:
        f.write(f"""def run_feature():
    # Goal: {goal}
    # Agent implemented logic:
    return "SUCCESS"
""")
    time.sleep(2)
    
    # 5. Final Test Run
    print("Step 5: Final Test Run (Expecting Success)...")
    res = subprocess.run(["pytest", test_file], capture_output=True, text=True)
    if res.returncode == 0:
        print("✅ TDD Cycle Complete! Tests are green.")
    else:
        print("❌ Final test failed. The loop would normally retry here.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: tdd_loop.py 'description of feature'")
        sys.exit(1)
    
    # Ensure pytest is installed for the demo to work
    try:
        import pytest
    except ImportError:
        print("Installing pytest for TDD Loop...")
        os.system(sys.executable + " -m pip install -q pytest")
        
    run_tdd(sys.argv[1])
