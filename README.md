# eBay Pictures Tool

The eBay Pictures Tool is a purpose-built application designed to streamline the image processing workflow for eBay listings. With
the added functionality to integrate with the Odoo ERP system, users can seamlessly handle images for their listings.

## Features

- **Image Processing**: Specifically tailored for eBay listings to ensure images fit eBay's recommended standards.
- **Odoo Integration**: Offers an option to automatically upload processed images directly to your Odoo instance.
- **User-friendly Interface**:Simple and intuitive setup and processing steps.

## Installation

### Prerequisites

The tool requires macOS Monterey or newer. If you're using an older version of macOS, the tool might not function as intended.

1. **Installation Command**:

   Open a terminal and run the following command:
   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/cbusillo/ebay_pictures_tool/main/installer.sh)"
   ```
   This command will download and execute the installation script from our GitHub repository.
   This installation might take some time, so please be patient. During the process, you might be prompted to enter your user
   password.

   Note: If the installation script indicates that the required developer tools are missing with an error message like:
   ```
   xcode-select: note: no developer tools were found at `Applications/Xcode.app`, requesting install.
   ```
   A dialog will prompt you to install the necessary tools. Click "Install" and once the installation is complete, you can continue
   with the eBay Pictures Tool installation.

2. **Odoo Configuration**:

   Once the eBay Pictures Tool is installed, it will execute and set up the environment. For integration with Odoo, configure
   the `secret.json` file located at `~/.shiny/secret.json`:

   - **Password**: To create an API Key, navigate to your Odoo instance, click your profile name at the top right, go to the "Account
     Security" tab, and select "NEW API KEY".

     ![API_Key_Screenshot.png](images/API_Key_Screenshot.png)

   - **Username**: Typically your Odoo username, which is often your email address.
   - **Database Name**: Activate the developer mode in Odoo. Once it's active, the database name is displayed near your username at
     the top right.
   - **URL**: The base URL for your Odoo instance (e.g., "http://shop.yourdomain.com").

   Your configuration should resemble:
   ```json
   {
       "odoo_url": "Website URL",
       "odoo_db": "Database Name",
       "odoo_username": "info@blah.com",
       "odoo_password": "PASSWORD"
   }
   ```

## Usage Guide

To use the `ebay_pictures_tool`, you can run it directly from the terminal. The tool accepts various arguments to customize its
behavior, as detailed below.

1. **Basic Command**:

```
ebay_pictures_tool
```

This will execute the tool with its default settings.

2. **Arguments**:

   - `-s` or `--sd_card_path`: Path to your SD card.
      - **Default**: `/Volumes/EOS_DIGITAL` (or `~/Desktop/Input` if in testing mode)
     ```
     ebay_pictures_tool -s /path/to/sd/card
     ```

   - `-o` or `--output_path`: Path to the directory where you want to save the processed images.
      - **Default**: `~/Desktop/eBay Pics`
     ```
     ebay_pictures_tool -o /path/to/output/directory
     ```

   - `-t` or `--trimmed_output_path`: Path to the directory where trimmed images will be saved.
      - **Default**: `~/Desktop/eBay Pics/Trimmed`
     ```
     ebay_pictures_tool -t /path/to/trimmed/output/directory
     ```

   - `-n` or `--nb_output_path`: Path to the directory where images without a background will be saved.
      - **Default**: `~/Desktop/eBay Pics/NB`
     ```
     ebay_pictures_tool -n /path/to/no/background/output/directory
     ```

   - `-b` or `--background_color`: Sets the background color for trimmed images in (R,G,B) format.
      - **Default**: `255,255,255`
     ```
     ebay_pictures_tool -b 255,255,255
     ```

   - `-m` or `--model_name`: Model name to use for background removal.
      - **Default**: `isnet-general-use`
         - `isnet-general-use`: This model is optimal for cleanly cutting out the primary object, but it will remove everything
           except the main subject.
         - `u2net`: This model doesn't cut as cleanly as `isnet-general-use`, but retains smaller parts in the pictures, such as
           screws or other minor details.
     ```
     ebay_pictures_tool -m model_name
     ```

You can combine multiple arguments in one command. For example, if you want to specify both the SD card path and the output
directory, you can run:

```
ebay_pictures_tool -s /path/to/sd/card -o /path/to/output/directory
```

For a complete list of options and their descriptions, you can run:

```
ebay_pictures_tool --help
```

## Troubleshooting

(*WIP*)

## Contributing and Feedback

Encountered any issues, have feature requests, or any other feedback? Please open an issue on
our [GitHub repository](https://github.com/cbusillo/ebay_pictures_tool).

## License

No idea

