# weather-web-app-june-2026

This is a simple web app that allows the user to look up the weather, and stores a history of lookups in a PostgreSQL database.

It uses the National Weather Service's API (api.weather.gov) for weather data. Since the NWS API requires lat/lon coordinates, OpenStreetMap's Nominatim API is used for geocoding.

Much of the code was generated using Anthropic's Claude Code LLM. Some changes did have to be made from what the model initially generated. These include: switching from server-side rendering to using a REST API and client-side AJAX, changing at least one API endpoint (/api/weather/) from POST to GET, and using password-based authentication for PostgreSQL instead of passwordless/trust authentication.

## Setup

### Database setup

You will need to do the following to set up the database:
* Ensure that PostgreSQL is installed. On an Ubuntu/Debian system, run `sudo apt-get update` and `sudo apt-get install postgresql`
* Run `CREATE DATABASE weather;` to create the table. At the terminal this can be done by logging in as a user that has a psql role, and running: `psql -h 127.0.0.1 -U postgres -c "CREATE DATABASE weather;"`
* Ensure that a psql role exists for the user that you are running as. So if your process is running as `myuser` then run: `psql -h 127.0.0.1 -U postgres -c "CREATE ROLE myuser SUPERUSER LOGIN;"
* Export your database username and password for the role to environment variables.

### Web app setup

To set up the web app:
* Make sure you have Python 3.x installed. Python 3.12-3.14 is recommended; the app has been tested to work on versions 3.12.3 and 3.14.3.
* Make sure your Python environment is set up. Especially if you are running Python for other purposes on your system, creating a virtual environment is recommended. To do this, run `python -m venv venv` to create the virtual environment, and run `source venv/bin/activate` to activate it.
* Install the required pip packages using: `pip install -r requirements.txt`
* You will need to export your psql credentials to environment variables `DB_USER` and `DB_PASSWORD`. This can be done one time by running `export DB_USER="yourusernamehere"` and `export DB_PASSWORD="yourpasswordhere"` in the terminal. Append these lines to the relevant config file for your shell (such as `~/.bashrc`) to make it do this every time you start the terminal.
* Run `python app.py` to start, and it will be running on port 5000 (http://localhost:5000 if it is running on your local system)

### Setting it up as a service

The previous instructions only start the app once. To make it start every time the system starts up, we'll need to install a systemd service.
* Open `service_file/weather-web-app.service` and update `User`, `WorkingDirectory`, and `ExecStart`. `User` should be the username of the user that runs the app, `WorkingDirectory` should be the root of this project, and `ExecStart` should be the location of your python executable. (The latter will likely be at `venv/bin/python3` within the `WorkingDirectory` if you created a venv. Otherwise, run `which python` to find the python executable you're using.)
* Copy `weather-web-app.service` to `/etc/systemd/system` using: `sudo cp service_file/weather-web-app.service /etc/systemd/system`
* You will also need to export the database user/pass as environment variables. One way to do this is to run `sudo systemctl edit weather-web-app`. Below the first set of comments, add a line `[Service]`, and below that add a line `Environment="DB_USER=yourusernamehere" "DB_PASSWORD=yourpasswordhere"` *(replacing these with your user/pass)*
