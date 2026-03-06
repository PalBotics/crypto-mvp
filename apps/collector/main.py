from core.app import bootstrap_app


def main() -> None:
    bootstrap_app(service_name="collector", check_db=True)


if __name__ == "__main__":
    main()