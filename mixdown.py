import subprocess
import zipfile
import tempfile
import shutil
import os
import re
from pathlib import Path
import io
from datetime import datetime, timedelta

# OGG files mixer - combines all OGG files into a single mixed track

# Timestamp pattern: MM.DD.YY-HH..MM-{TMZ}
TIMESTAMP_PATTERN = r'(\d{2}\.\d{2}\.\d{2}-\d{2}\.\.\d{2}-[A-Z]+)'

def extract_timestamp_from_filename(filename):
    """Extract timestamp from filename (e.g., '02.19.26-20..33-CST')"""
    match = re.search(TIMESTAMP_PATTERN, filename)
    if match:
        timestamp_str = match.group(1)
        # Parse: MM.DD.YY-HH..MM-TMZ (e.g., "02.19.26-20..33-CST")
        # Handle double dots in time: 20..33 = 20:33
        time_part = timestamp_str.split('-')[1].replace('..', ':')
        date_part = timestamp_str.split('-')[0]
        
        # Parse: MM.DD.YY format
        dt = datetime.strptime(f"{date_part} {time_part}", "%m.%d.%y %H:%M")
        return dt
    return None

def find_related_parts_by_time(zip_path, time_window_hours=6):
    """Find all related zip parts by analyzing timestamps - groups files within time window"""
    zip_path = Path(zip_path)
    directory = zip_path.parent
    
    # Extract timestamp from input file
    input_timestamp = extract_timestamp_from_filename(zip_path.name)
    if not input_timestamp:
        # Fallback to part suffix detection if no timestamp found
        print(f"⚠️  No timestamp found in {zip_path.name}, falling back to -partN detection")
        return find_related_parts_legacy(zip_path)
    
    print(f"📅 Detected timestamp: {input_timestamp.strftime('%Y-%m-%d %H:%M')}")
    
    # Extract the prefix (e.g., "8inf-recording" from "8inf-recording--02.19.26-20..33-CST")
    # The prefix is everything before the timestamp pattern
    prefix_match = re.match(r'^(.+?)--' + TIMESTAMP_PATTERN.replace('(', '(?P<ts>'), zip_path.stem)
    if prefix_match:
        file_prefix = prefix_match.group(1)  # e.g., "8inf-recording"
    else:
        # Fallback: use everything before the timestamp
        file_prefix = re.sub(r'--.*$', '', zip_path.stem)
    
    print(f"🏷️  Using prefix filter: '{file_prefix}'")
    
    # Find all zip files in directory
    all_zips = list(directory.glob('*.zip'))
    
    # Filter and sort by time difference AND prefix match
    related_files = []
    time_window = timedelta(hours=time_window_hours)
    
    for f in all_zips:
        # Check prefix match first
        f_prefix_match = re.match(r'^(.+?)--' + TIMESTAMP_PATTERN.replace('(', '(?P<ts>'), f.stem)
        if f_prefix_match:
            f_prefix = f_prefix_match.group(1)
        else:
            f_prefix = re.sub(r'--.*$', '', f.stem)
        
        # Skip if prefix doesn't match
        if f_prefix != file_prefix:
            continue
        
        other_timestamp = extract_timestamp_from_filename(f.name)
        if other_timestamp:
            time_diff = abs((other_timestamp - input_timestamp).total_seconds())
            if time_diff <= time_window.total_seconds():
                related_files.append((other_timestamp, f))
    
    # Sort by timestamp
    related_files.sort(key=lambda x: x[0])
    
    if not related_files:
        # Fallback to single file
        return [zip_path], zip_path.stem
    
    result = [f for _, f in related_files]
    
    # Generate a base name from the first file's timestamp
    first_ts = related_files[0][0]
    base_name = f"{zip_path.stem.split('--')[0]}--{first_ts.strftime('%m.%d.%y-%H..%M')}"
    # Remove timezone suffix for cleaner output name
    base_name = re.sub(r'-[A-Z]+$', '', base_name)
    
    return result, base_name

def find_related_parts_legacy(zip_path):
    """Legacy detection for -partN suffix pattern"""
    zip_path = Path(zip_path)
    directory = zip_path.parent
    stem = zip_path.stem
    
    part_match = re.match(r'^(.+?)-part(\d+)$', stem)
    if part_match:
        base_name = part_match.group(1)
    else:
        base_name = stem
    
    pattern = re.compile(rf'^{re.escape(base_name)}-part(\d+)\.zip$')
    related_files = []
    
    for f in directory.glob('*.zip'):
        match = pattern.match(f.name)
        if match:
            part_num = int(match.group(1))
            related_files.append((part_num, f))
    
    if not pattern.match(zip_path.name):
        related_files.append((0, zip_path))
    
    related_files.sort(key=lambda x: x[0])
    
    return [f for _, f in related_files], base_name

def find_related_parts(zip_path):
    """Find all related zip parts (e.g., recording-part1.zip, recording-part2.zip)"""
    # First try time-based detection
    return find_related_parts_by_time(zip_path, time_window_hours=6)

def remove_raw_dat_from_zip(zip_path):
    """Remove raw.dat file from the original zip file"""
    zip_path = Path(zip_path)
    
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        # Create a new zip in memory
        new_zip_data = io.BytesIO()

        with zipfile.ZipFile(new_zip_data, 'w', zipfile.ZIP_DEFLATED) as new_zip:
            # Copy all files except raw.dat
            for item in zip_ref.infolist():
                if item.filename != "raw.dat":
                    # Copy file data directly from original zip
                    new_zip.writestr(item, zip_ref.read(item.filename))
    
    # Write the modified zip data back to the original file
    with open(zip_path, 'wb') as f:
        f.write(new_zip_data.getvalue())
    print(f"🗑️  Removed raw.dat from {zip_path.name}")

def process_zip_in_memory(zip_path):
    """Process zip file entirely in memory without extracting to disk"""
    zip_path = Path(zip_path)
    
    if not zip_path.exists():
        raise FileNotFoundError(f"Zip file not found: {zip_path}")
    
    print(f"📦 Processing {zip_path.name} in memory...")
    
    # Read zip file into memory
    with open(zip_path, 'rb') as f:
        zip_data = io.BytesIO(f.read())
    
    with zipfile.ZipFile(zip_data, 'r') as zip_ref:
        # Find all OGG files in the zip
        ogg_files = []
        minerea_files = []
        other_files = []
        
        for item in zip_ref.infolist():
            if item.filename.endswith('.ogg'):
                # Read file content into memory
                file_data = zip_ref.read(item.filename)
                
                # Create a temporary file for ffmpeg to process
                # Keep original filename for speaker matching
                original_name = Path(item.filename).stem  # e.g., "4-_vz"
                temp_file = tempfile.NamedTemporaryFile(suffix='.ogg', delete=False)
                temp_file.write(file_data)
                temp_file.close()
                
                file_path = Path(temp_file.name)
                
                # Categorize files and store with original name
                file_info = (file_path, original_name)
                
                if "Minerea" in item.filename or "eara" in item.filename:
                    minerea_files.append(file_info)
                else:
                    other_files.append(file_info)
                
                ogg_files.append(file_info)
        
        print(f"🎵 Found {len(ogg_files)} OGG files total")
        
        if minerea_files:
            print(f"📊 Minerea/eara tracks: {len(minerea_files)}")
            for f, name in minerea_files:
                print(f"   - {name}")
        
        print(f"📊 Other tracks: {len(other_files)}")
        for f, name in other_files:
            print(f"   - {name}")
        
        # Return tuples for categorization, but also return just file paths for cleanup
        temp_files = [f for f, _ in ogg_files]
        
        return other_files, minerea_files, temp_files

def mix_files(ogg_files, output_path, minerea_files=None, mode="remove"):
    """Mix multiple OGG files into a single track using ffmpeg amix filter"""
    cmd = ["ffmpeg", "-y"]
    
    # Combine all files if mode is "lower"
    all_files = ogg_files if mode == "remove" else ogg_files + (minerea_files or [])
    
    # Add all input files
    for f in all_files:
        cmd.extend(["-i", str(f)])
    
    # Build filter chain:
    # 1. Resample each input to fix timing issues
    # 2. Apply volume adjustment to Minerea/eara tracks if mode is "lower"
    # 3. Mix all resampled inputs together
    num_inputs = len(all_files)
    num_normal = len(ogg_files)
    
    # Create aresample and volume filters for each input
    filter_parts = []
    for i in range(num_inputs):
        # Check if this is a Minerea/eara file (only when mode is "lower")
        is_minerea = mode == "lower" and i >= num_normal
        
        if is_minerea:
            # Resample + reduce volume by 30dB
            filter_parts.append(f"[{i}:a]aresample=async=1:first_pts=0,volume=-30dB[a{i}]")
        else:
            # Just resample
            filter_parts.append(f"[{i}:a]aresample=async=1:first_pts=0[a{i}]")
    
    # Mix all resampled streams
    mix_inputs = "".join(f"[a{i}]" for i in range(num_inputs))
    filter_parts.append(f"{mix_inputs}amix=inputs={num_inputs}:duration=longest:dropout_transition=0")
    
    # Combine filter chain
    filter_complex = ";".join(filter_parts)
    
    # Add filter complex and output
    cmd.extend(["-filter_complex", filter_complex, "-c:a", "libvorbis", "-q:a", "4", str(output_path)])
    
    # Run ffmpeg
    print(f"Running: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

def cleanup_temp_files(files):
    """Clean up temporary files"""
    for file_path in files:
        try:
            os.unlink(file_path)
        except:
            pass

def concatenate_ogg_files(ogg_files, output_path):
    """Concatenate multiple OGG files sequentially using ffmpeg concat demuxer"""
    if not ogg_files:
        return None
    
    if len(ogg_files) == 1:
        # Only one file, just copy it
        shutil.copy(ogg_files[0], output_path)
        return output_path
    
    # Create a temporary file list for ffmpeg concat
    list_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
    try:
        for f in ogg_files:
            # Escape single quotes in filename
            escaped_path = str(f).replace("'", "'\\''")
            list_file.write(f"file '{escaped_path}'\n")
        list_file.close()
        
        # Run ffmpeg concat
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", list_file.name,
            "-c", "copy", str(output_path)
        ]
        print(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        return output_path
    finally:
        try:
            os.unlink(list_file.name)
        except:
            pass

# Main execution function
def main():
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python mixdown.py <zip_file_path>")
        print("Example: python mixdown.py bridge_hours.zip")
        print("Example (multi-part): python mixdown.py recording-part1.zip")
        sys.exit(1)
    
    zip_path = sys.argv[1]
    
    # Find all related parts
    print(f"🔍 Looking for related parts of: {Path(zip_path).name}")
    part_files, base_name = find_related_parts(zip_path)
    
    if len(part_files) > 1:
        print(f"📦 Found {len(part_files)} parts:")
        for i, pf in enumerate(part_files):
            print(f"   Part {i+1}: {pf.name}")
    else:
        print(f"📦 Single file detected: {part_files[0].name}")
    
    # Clean base name for output (remove any -partN suffix)
    clean_base_name = re.sub(r'-part\d+$', '', base_name)
    
    # Process each part and collect files
    all_other_files = []
    all_minerea_files = []
    all_temp_files = []
    
    # Track files by part index: {part_idx: {'other': [...], 'minerea': [...]}}
    files_by_part = {}
    
    for part_idx, part_file in enumerate(part_files):
        print(f"\n{'='*50}")
        print(f"Processing part {part_idx + 1}/{len(part_files)}: {part_file.name}")
        print(f"{'='*50}")
        
        # Remove raw.dat from each part zip
        remove_raw_dat_from_zip(part_file)
        
        # Process zip file in memory
        other_files, minerea_files, temp_files = process_zip_in_memory(part_file)
        
        # Store files grouped by part
        files_by_part[part_idx] = {
            'other': other_files,
            'minerea': minerea_files
        }
        
        # Extend lists with tuples (file_path, speaker_name)
        all_other_files.extend(other_files)
        all_minerea_files.extend(minerea_files)
        # temp_files is now a list of file paths (not tuples)
        all_temp_files.extend(temp_files)
    
    if not all_other_files and not all_minerea_files:
        print("❌ No OGG files found in any zip!")
        sys.exit(1)
    
    # Create two mixdowns - one for each mode
    print(f"\n🎵 Creating mixdowns for: {clean_base_name}")
    
    # Mixdown for "remove" mode - mix each part, then concatenate
    print("\n🔧 Mixdown 1: MINEREA_MODE = 'remove'")
    output_file_remove = Path(f"{clean_base_name} - single.ogg")
    print("Excluding Minerea/eara tracks completely")
    
    # Create part mixes (without Minerea)
    part_mixes_remove = []
    for part_idx in sorted(files_by_part.keys()):
        other_files = files_by_part[part_idx].get('other', [])
        if not other_files:
            continue
        
        file_paths = [f for f, _ in other_files]
        part_mix = tempfile.NamedTemporaryFile(suffix='.ogg', delete=False)
        part_mix.close()
        mix_files(file_paths, part_mix.name, None, "remove")
        all_temp_files.append(Path(part_mix.name))
        part_mixes_remove.append(Path(part_mix.name))
        print(f"   ✅ Part {part_idx + 1} mix created")
    
    # Concatenate part mixes
    if len(part_mixes_remove) > 1:
        print(f"📎 Concatenating {len(part_mixes_remove)} part mixes...")
        concatenate_ogg_files(part_mixes_remove, output_file_remove)
    elif len(part_mixes_remove) == 1:
        shutil.copy(part_mixes_remove[0], output_file_remove)
    
    print(f"✅ Mixdown 1 complete! Saved to: {output_file_remove.absolute()}")
    
    # Mixdown for "lower" mode - mix each part with Minerea, then concatenate
    print("\n🔧 Mixdown 2: MINEREA_MODE = 'lower'")
    output_file_lower = Path(f"{clean_base_name} - single-bg.ogg")
    print("Including Minerea/eara tracks at -30dB")
    
    # Create part mixes (with Minerea)
    part_mixes_lower = []
    for part_idx in sorted(files_by_part.keys()):
        other_files = files_by_part[part_idx].get('other', [])
        minerea_files = files_by_part[part_idx].get('minerea', [])
        
        if not other_files and not minerea_files:
            continue
        
        file_paths = [f for f, _ in other_files]
        minerea_paths = [f for f, _ in minerea_files] if minerea_files else None
        
        part_mix = tempfile.NamedTemporaryFile(suffix='.ogg', delete=False)
        part_mix.close()
        mix_files(file_paths, part_mix.name, minerea_paths, "lower")
        all_temp_files.append(Path(part_mix.name))
        part_mixes_lower.append(Path(part_mix.name))
        print(f"   ✅ Part {part_idx + 1} mix with Minerea created")
    
    # Concatenate part mixes
    if len(part_mixes_lower) > 1:
        print(f"📎 Concatenating {len(part_mixes_lower)} part mixes...")
        concatenate_ogg_files(part_mixes_lower, output_file_lower)
    elif len(part_mixes_lower) == 1:
        shutil.copy(part_mixes_lower[0], output_file_lower)
    
    print(f"✅ Mixdown 2 complete! Saved to: {output_file_lower.absolute()}")
    
    # Clean up temporary files
    print(f"🧹 Cleaning up temporary files...")
    cleanup_temp_files(all_temp_files)
    print(f"✅ Cleanup complete!")

if __name__ == "__main__":
    main()