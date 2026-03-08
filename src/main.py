from utility import setup_env, setup_logging
from db_manager import StaffManager
import flask_bridge

def main():
    logger = None
    try:
        config, paths = setup_env()
        logger = setup_logging(paths['base'], config)
        logger.info("=== Application started ===")

        sm = StaffManager(paths, config)
        logger.info("StaffManager ready.")

        flask_bridge.init(sm, config, paths['base'], paths['data'], logger)
        flask_bridge.start()

    except Exception as e:
        msg = f"Startup error: {e}"
        (logger.error(msg, exc_info=True) if logger else print(f"[ERROR] {msg}"))

if __name__ == "__main__":
    main()
