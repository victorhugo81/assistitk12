---
title: "Bulk Upload Guide: Users & Sites CSV"
description: "How to format, download, and upload the users.csv and sites.csv files used to bulk-import users and school sites."
date: 2026-09-12
weight: 10
---

# Bulk Upload Guide: Users & Sites CSV

AssistITK12 supports bulk-importing **users** and **sites** from CSV files. This guide covers the required file format, column reference, and a ready-to-use template for each file.

Both files can be uploaded together or separately from the **Bulk Upload** page (**Settings → Data Integration → Bulk Upload**). If you upload both at once, **sites.csv is always processed first**, so new users can be assigned to sites created in the same upload.

---

## Before You Start

1. Download the template for the file you need (see each section below).
2. Fill in every row, keeping the header row exactly as provided — **do not rename, reorder, or remove columns**.
3. Save the file as UTF-8 encoded `.csv`.
4. Name the file exactly `users.csv` or `sites.csv` when uploading both at once (this is how the system tells them apart).
5. Upload the file(s) on the Bulk Upload page. You'll see a summary of how many records were added, updated, or marked inactive.

---

## users.csv

### Instructions

- Each row represents one user account.
- **Matching existing users:** a user is matched by `email`. If the email already exists, that user's record is **updated** (name, room, role, and site). If it doesn't exist, a **new user** is created with a random temporary password — they'll be required to set their own password on first login.
- **Deactivation:** any currently **Active** user who is *not* found in the uploaded file is automatically marked **Inactive**. Admin accounts (`role_id = 1`) are never auto-deactivated this way, so a file that omits an admin can't accidentally lock everyone out.
- The `site_name` value must exactly match an existing site's name in the system (or a site created by a `sites.csv` uploaded in the same batch).

### Column Reference

| Column | Required | Description | Example |
|---|---|---|---|
| `first_name` | Required | User's first name | `Maria` |
| `middle_name` | Optional | User's middle name | `Elena` |
| `last_name` | Required | User's last name | `Garcia` |
| `email` | Required | Unique email address — used to match existing users | `m.garcia@school.edu` |
| `role_id` | Required | Numeric role ID: `1` = Admin, `2` = Specialist, `3` = Technician, `4` = Teacher | `4` |
| `site_name` | Required | Exact site name as it appears in the system | `Lincoln Elementary` |
| `rm_num` | Required | Room number or location | `101` |
| `status` | Optional | Account status — defaults to `Active` if omitted | `Active` |

### Template

Download: `user_bulk_template_upload.csv`

```csv
first_name,middle_name,last_name,email,role_id,site_name,rm_num,status
Maria,Elena,Garcia,m.garcia@school.edu,4,Lincoln Elementary,101,Active
James,,Johnson,j.johnson@school.edu,4,Lincoln Elementary,102,Active
Priya,Ann,Patel,p.patel@school.edu,4,Washington Middle School,205,Active
Carlos,Luis,Rivera,c.rivera@school.edu,3,Washington Middle School,B12,Active
Sandra,,Kim,s.kim@school.edu,4,Roosevelt High School,301,Active
David,James,Nguyen,d.nguyen@school.edu,4,Roosevelt High School,302,Active
Emily,,Thompson,e.thompson@school.edu,2,Lincoln Elementary,Office,Active
Robert,Alan,Martinez,r.martinez@school.edu,4,Washington Middle School,210,Inactive
Jessica,,Lee,j.lee@school.edu,4,Roosevelt High School,115,Active
Michael,John,Brown,m.brown@school.edu,3,Lincoln Elementary,Lib,Active
```

---

## sites.csv

### Instructions

- Each row represents one school site.
- **Matching existing sites:** a site is matched by `site_name`. If the name already exists, that site's record is **updated**. If it doesn't exist, a **new site** is created.
- Only `site_name`, `site_acronyms`, `site_cds`, `site_code`, `site_address`, and `site_type` are required. The location and principal/contact columns are optional — leave a cell blank if you don't have that data.
- `site_cds` (California District/School code) can be pasted directly from Excel even if it's shown in scientific notation (e.g. `1.23457E+13`) — it's automatically converted back to a plain number.

### Column Reference

| Column | Required | Description | Example |
|---|---|---|---|
| `site_name` | Required | Unique site name — used to match existing sites | `Lincoln Elementary` |
| `site_acronyms` | Required | Site acronym | `LE` |
| `site_cds` | Required | CDS code | `12-73399-1232232` |
| `site_code` | Required | Short site code | `001` |
| `site_address` | Required | Street address | `123 Main St` |
| `sitecity` | Optional | City | `Anytown` |
| `sitestate` | Optional | State | `CA` |
| `sitezip` | Optional | Zip code | `12345` |
| `prnfirstn` | Optional | Principal's first name | `Alex` |
| `prnlastn` | Optional | Principal's last name | `Rivera` |
| `email` | Optional | Principal's email address | `a.rivera@school.edu` |
| `phone` | Optional | Principal's phone number | `555-123-4567` |
| `site_type` | Required | Site level or category | `Elementary`, `Middle`, `High` |

### Template

Download: `site_bulk_template_upload.csv`

```csv
site_name,site_acronyms,site_cds,site_code,site_address,sitecity,sitestate,sitezip,prnfirstn,prnlastn,email,phone,site_type
Lincoln Elementary,LE,12-73399-1232232,001,123 Main St,Anytown,CA,12345,Alex,Rivera,a.rivera@school.edu,555-123-4567,Elementary
Washington Middle School,WMS,12-73399-1232233,002,456 Oak Ave,Anytown,CA,12345,Jordan,Kim,j.kim@school.edu,555-123-4568,Middle
Roosevelt High School,RHS,12-73399-1232234,003,789 Pine Rd,Anytown,CA,12345,Priya,Patel,p.patel@school.edu,555-123-4569,High
```

---

## Troubleshooting

| Problem | Cause | Fix |
|---|---|---|
| "Some rows in the CSV file are missing required fields." | A required column is empty for one or more rows. | Fill in every required column for every row. |
| "Site '...' not found. Please verify the CSV file." | A user's `site_name` doesn't match any existing site. | Check spelling/capitalization, or include that site in a `sites.csv` uploaded in the same batch. |
| "Row N is missing required fields: ..." | A `sites.csv` row is missing a required column. | Fill in the listed columns for that row. |
| Import fails with an encoding error | The file wasn't saved as UTF-8. | Re-save the CSV with UTF-8 encoding before uploading. |
| Active user unexpectedly marked Inactive | They were left out of the uploaded `users.csv`. | Include every currently active user in each upload, or add them back manually afterward. |
