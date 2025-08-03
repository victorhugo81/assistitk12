# AssistITK12

![AssistITK12 Logo](https://assistitk12.com/wp-content/uploads/2025/05/logo.png) 

AssistITk12 is a web-based ticketing system designed to help school districts manage support requests, maintenance issues, and other technical problems. It's built with Flask and Bootstrap to provide a user-friendly and efficient solution.

[AssistITk12.com](https://assistitk12.com) 

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

### Prerequisites Dependencies

- [Git](https://git-scm.com/downloads/linux)
- [UV: Ultra fast Python package manager](https://docs.astral.sh/uv/getting-started/installation/#standalone-installer)
- [Python 3.12.x](https://docs.astral.sh/uv/concepts/python-versions/#installing-a-python-version)
- [MySQL Server](https://dev.mysql.com/doc/mysql-getting-started/en/)


### Step 1: Clone the ASSISTITK12 repository

```bash
git clone https://github.com/victorhugo81/assistitk12
cd assistitk12
```

### Step 2: Set up a virtual environment
Choose the instructions appropriate for your OS.
**Windows:**
```bash
uv venv .venv
.venv\Scripts\activate
```

**MacOS/Linux:**
```bash
uv venv .venv
source .venv/bin/activate
```

### Step 3:  Initialize UV project and install dependencies

```bash
uv init
uv pip install -r requirements.txt
```

### Step 4: APP Database Setup
Important: Don't commit your .env file to version control. Make sure it's added to .gitignore to protect sensitive information!

These script creates:
- Default ticket statuses (Open, In Progress, Completed)
- Priority levels (Low, Medium, High, Critical)
- Common issue categories
- An .env file that contains configuration settings and secrets such as API keys, database credentials, or Flask settings outside your source code.

1. **Create .env file and MySQL database**
This script will create a file named .env in your project's root directory.
Edit the generated .env to use your actual database values.

```bash
python create_env.py 
```

   ```
   # .env file
   # An Application SECRET_KEY is a randomly generated string of characters used for security purposes.
   SECRET_KEY=your_secure_random_key_here

   # Database Connection URI
   DATABASE_URL=mysql+pymysql://username:password@localhost/assistitk12
   ```

2. **Seed database with initial app data**
Run the seed script to populate the database with initial data (including status types, priority levels, and categories):

```bash
python seed_data.py 
   ```


### Step 5: Start Flask development server

```bash
flask --app main.py run
```



## Usage

### Accessing the application

Open a web browser and navigate to the URL displayed in your terminal (usually http://127.0.0.1:5000/).

### Login

Enter the admin email and password you previously configured.
- Password must be over 10 characters long, contain letters and numbers, and special characters.

![Login Screen](https://assistitk12.com/wp-content/uploads/2025/05/screenshot-login.png) <!-- Add a login screen screenshot here -->

### Dashboard - Data Visualization

The dashboard provides an overview of all tickets, their statuses, and key metrics to help identify trends and areas for improvement.

![Dashboard](https://assistitk12.com/wp-content/uploads/2025/05/screenshot-dashboard-scaled.png) <!-- Add a dashboard screenshot here -->

### Creating a ticket

1. Click on Tickets sidebar
1. Click the "Add Ticket" button
2. Fill in the required details
3. Click the "Submit Ticket" button

![Create Ticket](https://assistitk12.com/wp-content/uploads/2025/05/screenshot-new-ticket-1536x820.png) <!-- Create a new ticket screenshot here -->

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
uv pip install -r requirements.txt --upgrade
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

## Project Structure Tree

```
assistitk12/
├── application/
│   ├── __init__.py
│   ├── models.py
│   ├── forms.py
│   ├── routes.py
│   ├── static/
│   │   ├── css/
│   │   ├── js/
│   │   ├── img/
│   │   └── uploads/
│   └── templates/
│       ├── includes/
│       │   ├── footer.html
│       │   └── nav.html
│       ├── add_notification.html
│       ├── add_role.html
│       ├── add_site.html
│       ├── add_ticket.html
│       ├── add_title.html
│       ├── add_user.html
│       ├── base.html
│       ├── edit_notification.html
│       ├── edit_role.html
│       ├── edit_site.html
│       ├── edit_ticket.html
│       ├── edit_title.html
│       ├── edit_user.html
│       ├── error.html
│       ├── index.html
│       ├── login.html
│       ├── notification.html
│       ├── organization.html
│       ├── profile.html
│       ├── roles.html
│       ├── sites.html
│       ├── tickets.html
│       ├── titles.html
│       └── users.html
├── main.py
├── config.py
├── requirements.txt
└── installation/
    ├── create_env.py
    └── seed_data.py
```

