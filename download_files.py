import argparse
import asyncio
import os
import re
import time
from datetime import datetime, timezone
from playwright.async_api import async_playwright


async def find_button_by_text(page, text: str, exact: bool = True):
    """Find a visible button by its text content. Returns the last match if multiple found."""
    all_buttons = page.locator('button')
    count = await all_buttons.count()
    candidates = []

    for i in range(count):
        try:
            button = all_buttons.nth(i)
            button_text = await button.text_content()
            visible = await button.is_visible()
            match = button_text.strip() == text if exact else text in button_text
            if match and visible:
                candidates.append((i, button))
        except:
            continue

    if not candidates:
        raise Exception(f"Could not find the {text} button")

    index, download_button = candidates[-1]
    print(f"Found {text} button at index {index} (last of {len(candidates)} candidates)")

    return download_button


async def check_previous_download(page):
    """Check if a previous download is available. Returns the download button or None."""
    try:
        heading = page.locator('h2:has-text("Previous Download")').first
        await heading.wait_for(state='visible', timeout=2000)

        # Navigate up to the section container and find the Download button within it
        section = heading.locator('..').locator('..')
        button = section.locator('button:has-text("Download")').first
        print("Found previous download!")
        return button
    except:
        return None


async def find_ogg_vorbis_button(page):
    """Find the Ogg Vorbis format button in the Downloads section (not Previous Download)."""
    all_buttons = page.locator('button')
    count = await all_buttons.count()

    for i in range(count):
        try:
            button = all_buttons.nth(i)
            text = await button.text_content()

            if 'Ogg Vorbis' not in text:
                continue

            # Confirm it's not inside a Previous Download section
            parent_html = await button.locator('..').locator('..').locator('..').inner_html()
            if 'Previous Download' not in parent_html:
                print(f"Found Ogg Vorbis button at index {i}")
                return button
        except:
            continue

    return None


async def trigger_new_encoding(page):
    """Open the Ogg Vorbis modal, check Normalize, and click Download to start encoding."""
    ogg_button = await find_ogg_vorbis_button(page)
    if not ogg_button:
        raise Exception("Could not find the Ogg Vorbis button in the Downloads section")

    print("Clicking the Ogg Vorbis button...")
    await ogg_button.click()

    print("Waiting for download dialog to appear...")
    await page.wait_for_timeout(2500)

    print("Checking 'Normalize audio' checkbox...")
    await page.get_by_text("Normalize audio").first.click()
    await page.wait_for_timeout(2500)

    # The modal's Download button is the last visible "Download" button on the page
    button = await find_button_by_text(page, "Download", exact=True)

    print("Clicking Download. Encoding process started — this may take several minutes...")
    async with page.expect_download(timeout=600000) as download_info:
        await button.click()

    return await download_info.value


async def save_download(download, output_dir: str, recording_data=None, fallback_name="8inf-recording", part_number=None):
    """Save a Playwright download object to the specified directory."""
    # Always generate a custom filename
    filename = generate_filename(recording_data, fallback_name, part_number=part_number)
    
    output_path = os.path.join(output_dir, filename)
    print(f"Saving file to: {output_path}")
    await download.save_as(output_path)
    print("Download completed successfully!")


def get_timezone_abbreviation(dt_local):
    """Get a short timezone abbreviation from a datetime object."""
    # First try strftime
    tz_name = dt_local.strftime('%Z')
    
    # If empty or too long, use time.tzname
    if not tz_name or tz_name == '' or len(tz_name) > 5:
        # Check if we're in daylight saving time
        is_dst = time.localtime().tm_isdst
        tz_names = time.tzname
        if is_dst and len(tz_names) > 1:
            tz_name = tz_names[1]  # Daylight saving time name
        else:
            tz_name = tz_names[0]  # Standard time name
    
    # Create abbreviation from capital letters in the timezone name
    if len(tz_name) > 3:
        # Extract capital letters from the timezone name
        capital_letters = ''.join([c for c in tz_name if c.isupper()])
        
        if capital_letters and len(capital_letters) >= 2:
            # Use the capital letters as abbreviation (e.g., "EST" from "Eastern Standard Time")
            tz_name = capital_letters
        else:
            # If no capital letters, take first 3 characters
            tz_name = tz_name[:3].upper()
    
    return tz_name


def generate_filename(recording_data=None, fallback_name="8inf-recording", part_number=None):
    """Generate a filename based on recording data or current timestamp."""
    part_suffix = f"-part{part_number}" if part_number else ""
    try:
        if recording_data and 'startTime' in recording_data:
            # Parse the ISO format datetime
            start_time_str = recording_data['startTime']
            
            # Parse the ISO format string as UTC
            dt_utc = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')).replace(tzinfo=timezone.utc)
            
            # Convert to local timezone
            dt_local = dt_utc.astimezone()
            
            tz_name = get_timezone_abbreviation(dt_local)
            
            # Format as mm.dd.yy-HHMMSS-TZ
            date_part = dt_local.strftime('%m.%d.%y-%H..%M')
            
            filename = f"{fallback_name}--{date_part}-{tz_name}{part_suffix}.zip"
            
    except Exception as e:
        print(f"Error generating filename, using fallback: {e}")
        # Add part number suffix if provided
        filename = f"{fallback_name}{part_suffix}.zip"
    
    return filename


async def download_assets(url: str, output_dir: str, skip_avatars: bool = False, part_number=None, debug=False):
    print(f"Starting Playwright to navigate to: {url} - debug={debug}")
    os.makedirs(output_dir, exist_ok=True)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=not debug) # Set headless=True to run without opening a browser window
        context = await browser.new_context(accept_downloads=True)
        page = await context.new_page()

        try:
            print("Navigating to the Craig download page...")
            await page.goto(url)
            await page.wait_for_load_state("networkidle")

            # Extract recording data from the page
            print("Extracting recording data from page...")
            recording_data = await extract_recording_data(page)

            # Download avatars if requested
            if not skip_avatars:
                print("Attempting to download avatars...")
                await download_avatars(page, output_dir, recording_data, part_number=part_number)
                print("Proceeding with audio download...")

            print("Checking for previous downloads...")
            prev_button = await check_previous_download(page)

            if prev_button:
                # A previous encoding is ready — download it directly
                print("Downloading previous encoding...")
                async with page.expect_download(timeout=60000) as download_info:
                    await prev_button.click()
                download = await download_info.value
            else:
                # No previous download — trigger a new encoding and wait for it
                print("No previous download found. Starting new encoding process...")
                download = await trigger_new_encoding(page)

            await save_download(download, output_dir, recording_data, part_number=part_number)

        except Exception as e:
            print(f"An error occurred: {e}")
            print("Make sure the link is valid and contains an Ogg Vorbis download option.")
            print("If encoding takes too long, you may need to increase the timeout.")

        finally:
            if not debug:
                await browser.close()


async def download_avatars(page, output_dir: str, recording_data=None, part_number=None):
    """Find and click the Download Avatars button to download avatars ZIP file."""
    print("Looking for Download Avatars button...")
    
    button = await find_button_by_text(page, "Download Avatars", exact=False)
    
    print("Clicking Download Avatars button...")
    try:
        async with page.expect_download(timeout=60000) as download_info:
            await button.click()
        
        download = await download_info.value
        
        # Save the download with custom filename
        await save_download(download, output_dir, recording_data, fallback_name="8inf-avatars", part_number=part_number)
        print("Avatars downloaded successfully!")
        await page.wait_for_timeout(2000)  # Wait a bit before proceeding to audio download
        return True
    except Exception as e:
        print(f"Error downloading avatars: {e}")
        return False


async def extract_recording_data(page):
    """Extract recording data from the page script tag."""
    try:
        # Get the page content
        content = await page.content()
        
        # Debug: Save content to file for inspection
        with open('page_content_debug.html', 'w', encoding='utf-8') as f:
            f.write(content)
        print("Saved page content to page_content_debug.html for inspection")
        
        # Simple regex to find startTime
        start_time_match = re.search(r'startTime:\s*"([^"]+)"', content)
        if not start_time_match:
            # Try with single quotes
            start_time_match = re.search(r"startTime:\s*'([^']+)'", content)
        
        start_time = start_time_match.group(1) if start_time_match else None
        
        if start_time:
            print(f"Extracted recording data: startTime={start_time}")
            return {
                'startTime': start_time
            }
        else:
            print("Could not extract startTime from page")
            return None
        
    except Exception as e:
        print(f"Error extracting recording data: {e}")
        return None


if __name__ == "__main__":
    # Hardcoded URL backup for easy testing. Replace with your actual Craig link!
    HARDCODED_URL = "https://craig.horse/rec/adD2wGZXLDhi?key=KXQpWb"
    debug = False  # Set to True to open window for debugging
    
    parser = argparse.ArgumentParser(description="Automate downloading OGG Vorbis from a Craig Discord bot link.")
    # nargs="*" allows multiple URLs (up to 4)
    parser.add_argument("urls", nargs="*", default=[HARDCODED_URL], help="The Craig download URLs (up to 4)")
    parser.add_argument("-o", "--outdir", default=".", help="Output directory (default: current directory)")
    parser.add_argument("--skip-avatars", action="store_true", help="Skip downloading avatars")
    
    args = parser.parse_args()
    
    # Limit to 4 URLs maximum
    urls = args.urls[:4]
    
    if len(urls) == 1 and urls[0] == "https://craig.horse/rec/adD2wGZXLDhi?key=KXQpWb":
        print("Warning: Running with the placeholder HARDCODED_URL! Please update the script or pass real URLs.")
    
    # Process each URL with part numbering (only for multiple URLs)
    for i, url in enumerate(urls, 1):
        print(f"\n=== Processing URL {i} of {len(urls)} ===")
        # Only use part numbers when there are multiple URLs
        part_number = i if len(urls) > 1 else None
        asyncio.run(download_assets(url, args.outdir, args.skip_avatars, part_number=part_number, debug=debug))