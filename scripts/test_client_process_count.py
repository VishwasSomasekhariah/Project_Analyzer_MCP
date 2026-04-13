#!/usr/bin/env python3
"""
Test to verify: Does keeping multiple ClaudeSDKClient instances alive
spawn multiple Claude CLI processes?

We'll:
1. Check baseline process count
2. Create 3 ClaudeSDKClient instances and keep them alive
3. Check process count again
4. Close clients and verify cleanup
"""

import asyncio
import subprocess
import time
from claude_agent_sdk import ClaudeSDKClient, ClaudeAgentOptions

def count_claude_processes():
    """Count running 'claude' processes."""
    result = subprocess.run(
        ["ps", "aux"],
        capture_output=True,
        text=True
    )

    # Count lines with 'claude' but exclude this script and grep
    lines = result.stdout.split('\n')
    claude_procs = [
        line for line in lines
        if 'claude' in line.lower()
        and 'grep' not in line
        and 'test_client_process_count' not in line
    ]

    return len(claude_procs), claude_procs

async def main():
    print("="*80)
    print("Testing: Does keeping ClaudeSDKClient alive spawn Claude CLI processes?")
    print("="*80)

    # Step 1: Baseline
    print("\n📊 STEP 1: Baseline (no clients)")
    baseline_count, baseline_procs = count_claude_processes()
    print(f"   Claude processes: {baseline_count}")
    if baseline_procs:
        print("   Processes:")
        for proc in baseline_procs[:3]:
            print(f"     {proc[:100]}")

    # Step 2: Create 3 clients and keep alive
    print("\n📊 STEP 2: Creating 3 ClaudeSDKClient instances...")

    clients = []

    for i in range(3):
        print(f"\n   Creating client {i+1}/3...")
        options = ClaudeAgentOptions(
            model="claude-sonnet-4-5-20250929",
            system_prompt=f"You are agent {i+1}",
            max_turns=1,
        )
        client = ClaudeSDKClient(options=options)
        await client.__aenter__()  # Enter context manager but don't exit
        clients.append(client)
        print(f"   ✅ Client {i+1} created and active")

        # Check process count after each client
        time.sleep(2)  # Give processes time to spawn
        count, procs = count_claude_processes()
        print(f"   📈 Process count after client {i+1}: {count} (delta: +{count - baseline_count})")

    # Step 3: Final count with all clients alive
    print("\n📊 STEP 3: All 3 clients alive")
    final_count, final_procs = count_claude_processes()
    print(f"   Claude processes: {final_count}")
    print(f"   Delta from baseline: +{final_count - baseline_count}")

    if final_count > baseline_count:
        print(f"\n   🔴 RESULT: {final_count - baseline_count} NEW processes spawned!")
        print("   New processes:")
        for proc in final_procs[:10]:
            print(f"     {proc[:120]}")
    else:
        print(f"\n   ✅ RESULT: No new processes spawned (uses API directly)")

    # Step 4: Query one client to see what happens
    print("\n📊 STEP 4: Querying client 1 to trigger initialization...")
    try:
        await asyncio.wait_for(
            clients[0].query("What is 2+2? Reply with just the number."),
            timeout=30
        )

        # Check for response (may spawn process during query)
        count_after_query, _ = count_claude_processes()
        print(f"   Process count after query: {count_after_query}")
        print(f"   Delta: +{count_after_query - final_count}")

        # Consume response
        async for message in clients[0].receive_response():
            pass  # Just consume, don't print

    except asyncio.TimeoutError:
        print("   ⚠️ Query timed out (expected for first query)")
    except Exception as e:
        print(f"   ⚠️ Query error: {e}")

    # Final process check
    post_query_count, post_query_procs = count_claude_processes()
    print(f"\n   Final process count: {post_query_count}")

    # Step 5: Cleanup
    print("\n📊 STEP 5: Closing all clients...")
    for i, client in enumerate(clients):
        await client.__aexit__(None, None, None)
        print(f"   ✅ Client {i+1} closed")

    time.sleep(2)  # Give processes time to terminate
    cleanup_count, cleanup_procs = count_claude_processes()
    print(f"\n   Process count after cleanup: {cleanup_count}")
    print(f"   Returned to baseline: {'✅ Yes' if cleanup_count == baseline_count else '❌ No'}")

    # Summary
    print("\n" + "="*80)
    print("📊 SUMMARY")
    print("="*80)
    print(f"Baseline processes:        {baseline_count}")
    print(f"After creating 3 clients:  {final_count} (delta: +{final_count - baseline_count})")
    print(f"After first query:         {post_query_count} (delta: +{post_query_count - final_count})")
    print(f"After cleanup:             {cleanup_count} (delta: {cleanup_count - baseline_count})")

    if final_count > baseline_count + 1:
        print("\n🔴 CONCLUSION: Each ClaudeSDKClient spawns a separate process!")
        print(f"   Keeping 3 clients alive = {final_count - baseline_count} processes")
        print("   ⚠️ This is a problem for keeping clients alive!")
    elif post_query_count > baseline_count:
        print("\n🟡 CONCLUSION: Query triggers process spawn (not client creation)")
        print(f"   All queries share same process")
        print("   ✅ Keeping clients alive is safe")
    else:
        print("\n✅ CONCLUSION: No processes spawned (uses API directly)")
        print("   ✅ Keeping clients alive is completely safe")

if __name__ == "__main__":
    asyncio.run(main())
