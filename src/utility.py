import sys, os, logging, yaml

def setup_env() -> tuple:
    base = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
            else os.path.dirname(os.path.dirname(__file__)))
    config = yaml.safe_load(open(os.path.join(base, "config.yaml")))
    paths  = {k: os.path.join(base, v) if k != 'base' else base
              for k, v in [('base', ''), ('data', config["path"]["data"]), ('log', config["path"]["log"])]}
    paths['base'] = base
    return config, paths

def setup_logging(base_path, config) -> logging.Logger:
    log_dir = os.path.join(base_path, config["path"]["log"])
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(
        filename=os.path.join(log_dir, "staff_scheduler.log"),
        filemode='a', level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.getLogger('').addHandler(logging.StreamHandler())
    return logging.getLogger(__name__)
