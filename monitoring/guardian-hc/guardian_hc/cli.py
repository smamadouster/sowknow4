"""Guardian HC CLI."""
import sys
import asyncio


def main():
    if len(sys.argv) < 2:
        print("Guardian HC v1.3.0 -- Self-Healing Health Check for SOWKNOW4")
        print("\nUsage:")
        print("  guardian-hc run [config.yml]     Start monitoring")
        print("  guardian-hc check [config.yml]   Run one check cycle")
        print("  guardian-hc preflight [dir]      Pre-flight validation")
        print("  guardian-hc install [dir]        Install watchdog cron")
        return

    cmd = sys.argv[1]
    config_path = sys.argv[2] if len(sys.argv) > 2 else "guardian-hc.yml"

    if cmd == "run":
        from guardian_hc.core import GuardianHC
        guardian = GuardianHC.from_config(config_path)
        asyncio.run(guardian.run())
    elif cmd == "check":
        from guardian_hc.core import GuardianHC
        guardian = GuardianHC.from_config(config_path)
        result = asyncio.run(guardian.run_check_cycle("deep"))
        import json
        print(json.dumps(result, indent=2))
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
