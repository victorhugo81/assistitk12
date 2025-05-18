# AssistITK12

AssistITk12 is a web-based ticketing system designed to help school districts manage support requests, maintenance issues, and other technical problems. It's built with Flask and Bootstrap to provide a user-friendly and efficient solution.

![AssistITK12 Logo](path/to/logo.png) <!-- Add your logo image here -->

## Features

- **Issue tracking**: Create, manage, and track support tickets.
- **Prioritization**: Assign priorities to tickets to ensure critical issues are addressed first.
- **User management**: Create and manage user accounts with different levels of access.
- **Reporting**: Generate reports to track trends and identify areas for improvement.
- **Customization**: Customize the look and feel of the application to match your school's branding.
- **Data Visualization**: Generate charts and graphs to visualize common technical issues and trends.

## Application Versions

- **Python 3.12.9**
- **Flask 3.1.0**
- **See requirements.txt** for a complete enumeration of package dependencies

## Installation

### Prerequisites

- Python 3.12.x
- MySQL Server
- Git

### Step 1: Clone the repository

```bash
git clone https://github.com/victorhugo81/assistitk12
cd assistitk12
```

### Step 2: Set up a virtual environment

**Windows:**
```bash
python -m pip install venv
python -m venv myenv
myenv\Scripts\activate
```

**MacOS/Linux:**
```bash
pip install virtualenv
python3 -m venv myenv
source myenv/bin/activate
```

### Step 3: Install dependencies

```bash
pip install -r requirements.txt
```

### Step 4: Database Setup

1. **Create database**: Create a new MySQL database for AssistITk12. You can do this via a MySQL client (like MySQL Workbench or phpMyAdmin), or via command line:

   ```sql
   CREATE DATABASE assistitk12;
   ```

2. **Configure environment variables**: Create a file named `.env` in your project's root directory:

   ```
   # .env file
   # An Application SECRET_KEY is a randomly generated string of characters used for security purposes.
   SECRET_KEY=your_secure_random_key_here

   # Database Connection URI
   DATABASE_URL=mysql+pymysql://username:password@localhost/assistitk12

   # Admin user configuration
   # IMPORTANT: Delete or comment out these lines after creating the admin user
   DEFAULT_ADMIN_EMAIL=admin@yourdomain.edu
   DEFAULT_ADMIN_PASSWORD=secure_admin_password
   DEFAULT_ADMIN_FIRST_NAME=Admin
   DEFAULT_ADMIN_LAST_NAME=User
   ```

   Replace the placeholders with your actual values.

### Step 5: Initialize the database

Run the Flask application to create the database tables:

```bash
flask --app main.py run
```

After the tables are created, stop the application with `Ctrl+C`.

### Step 6: Seed initial data

Run the seed script to populate the database with initial data (including status types, priority levels, and categories):

```bash
python seed.py
```

This script creates:
- Default ticket statuses (Open, In Progress, Completed)
- Priority levels (Low, Medium, High, Critical)
- Common issue categories
- The admin user specified in your `.env` file

### Step 7: Run the application

```bash
flask --app main.py run
```

## Usage

### Accessing the application

Open a web browser and navigate to the URL displayed in your terminal (usually http://127.0.0.1:5000/).

### Login

Enter the admin email and password you previously configured. 
- Password must be over 10 characters long, contain letters and numbers, and special characters.

![Login Screen](path/to/login_screenshot.png) <!-- Add a login screen screenshot here -->

### Dashboard - Data Visualization

The dashboard provides an overview of all tickets, their statuses, and key metrics to help identify trends and areas for improvement.

![Dashboard](path/to/dashboard_screenshot.png) <!-- Add a dashboard screenshot here -->

### Creating a ticket

1. Click on Tickets sidebar
1. Click the "Add Ticket" button
2. Fill in the required details
3. Click the "Submit Ticket" button

![Create Ticket](path/to/new_ticket_screenshot.png) <!-- Create a new ticket screenshot here -->

## Troubleshooting
### Database Connection Issues

- Ensure your MySQL server is running
- Verify the credentials in your `.env` file
- Check that the specified database exists

### Migration Errors

If you encounter database migration errors:

```bash
flask db upgrade
```

### Missing Dependencies

If you encounter missing module errors:

```bash
pip install -r requirements.txt --upgrade
```

## Production Deployment

For production environments:

1. Use a production WSGI server like Gunicorn:
   ```bash
   pip install gunicorn
   gunicorn -w 4 "main:create_app()"
   ```

2. Set up a reverse proxy with Nginx or Apache

3. Update your `.env` file with production settings

## Contributing

We welcome contributions from the community!

1. Fork the repository
2. Create a new branch:
   ```bash
   git checkout -b feature-branch
   ```
3. Make your changes and commit them:
   ```bash
   git commit -m "Description of your changes"
   ```
4. Push to the branch:
   ```bash
   git push origin feature-branch
   ```
5. Create a pull request on GitHub

## License

AssistITk12 is licensed under the GNU General Public License v3. See the LICENSE.txt file for more details.

## Contact

For questions or suggestions, please open an issue on GitHub or contact me at assistitk12@victorhugosolis.com.

## Disclaimer

AssistITk12 is still under development and may contain bugs or limitations. We are committed to improving the software and welcome your feedback.
