"""Use pytest for the isolated regression suite; never clear an application database."""
if __name__=="__main__":
    import subprocess,sys
    raise SystemExit(subprocess.call([sys.executable,"-m","pytest","tests"]))
