"""Nuitka entrypoint: resolve embedded assets before application startup."""
from neyra.bundled import configure_bundled_runtime

if __name__ == "__main__":
    configure_bundled_runtime()
    from neyra.main import main
    main()
