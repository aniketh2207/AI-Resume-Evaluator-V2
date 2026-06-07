import io
from typing import List, Dict, Any
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

import os
from app.core.config import backend_dir

# Configuration
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = os.path.join(backend_dir, 'ai-resume-evaluator-498012-305d5547940c.json')

def get_drive_service():
    """Authenticates using the Service Account and returns the Drive API service."""
    try:
        creds = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_FILE, scopes=SCOPES
        )
        service = build('drive', 'v3', credentials=creds)
        return service
    except Exception as e:
        print(f"Authentication Failed: {e}")
        raise

def fetch_unprocessed_resumes(unprocessed_folder_id: str) -> List[Dict[str, Any]]:
    """
    Queries the specified Google Drive folder for PDF files and downloads them into memory.
    
    Args:
        unprocessed_folder_id (str): The Google Drive Folder ID containing new resumes.
        
    Returns:
        List[Dict]: A list containing the file ID, file name, and the raw PDF bytes.
    """
    service = get_drive_service()
    resumes = []
    page_token = None

    try:
        while True:
            # Query strictly for PDFs inside the unprocessed folder
            query = f"mimeType='application/pdf' and parents in '{unprocessed_folder_id}' and trashed=false"
            
            response = service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name)',
                pageToken=page_token
            ).execute()

            for file in response.get('files', []):
                file_id = file.get('id')
                file_name = file.get('name')
                
                # Download the file content into memory (BytesIO)
                request = service.files().get_media(fileId=file_id)
                file_stream = io.BytesIO()
                downloader = MediaIoBaseDownload(file_stream, request)
                
                done = False
                while done is False:
                    status, done = downloader.next_chunk()
                
                resumes.append({
                    "file_id": file_id,
                    "file_name": file_name,
                    "pdf_bytes": file_stream.getvalue()
                })
                print(f"Downloaded into memory: {file_name}")

            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break
                
        return resumes

    except HttpError as error:
        print(f"An error occurred fetching files: {error}")
        return []

def move_to_processed(file_id: str, current_folder_id: str, processed_folder_id: str) -> bool:
    """
    Moves a file in Google Drive by altering its parent folders.
    
    Args:
        file_id (str): The ID of the file to move.
        current_folder_id (str): The ID of the 'Unprocessed' folder.
        processed_folder_id (str): The ID of the 'Processed' folder.
        
    Returns:
        bool: True if successful, False otherwise.
    """
    service = get_drive_service()
    
    try:
        # The Drive API moves files by adding the new parent and removing the old one
        service.files().update(
            fileId=file_id,
            addParents=processed_folder_id,
            removeParents=current_folder_id,
            fields='id, parents'
        ).execute()
        
        print(f"Successfully moved file ID {file_id} to Processed folder.")
        return True
        
    except HttpError as error:
        print(f"An error occurred moving the file: {error}")
        return False

def resolve_job_folders(job_name: str) -> dict:
    """
    Finds the 'ATS Master Folder'.
    Then finds the job folder named `job_name` inside it.
    Then finds two subfolders inside the job folder named 'Unprocessed' and 'Processed'.
    Returns a dict with 'unprocessed_id' and 'processed_id'.
    """
    service = get_drive_service()
    
    # 1. Search for 'ATS Master Folder'
    master_query = "name = 'ATS Master Folder' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    try:
        response = service.files().list(
            q=master_query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        files = response.get('files', [])
        if not files:
            raise ValueError(
                "Could not find the 'ATS Master Folder' on Google Drive. "
                "Please make sure it exists and has been shared with the service account email: "
                "ai-resume-evalutor@ai-resume-evaluator-498012.iam.gserviceaccount.com"
            )
            
        master_folder_id = files[0]['id']
        
        # 2. Search for the job folder inside 'ATS Master Folder'
        escaped_name = job_name.replace("'", "\\'")
        query = f"name = '{escaped_name}' and parents in '{master_folder_id}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        
        job_response = service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        job_files = job_response.get('files', [])
        if not job_files:
            raise ValueError(
                f"Could not find a Google Drive folder named '{job_name}' inside 'ATS Master Folder'."
            )
            
        parent_id = job_files[0]['id']
        
        # 3. Now find Unprocessed and Processed subfolders inside parent_id
        subfolders_query = f"parents in '{parent_id}' and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
        subfolders_response = service.files().list(
            q=subfolders_query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()
        
        subfolders = subfolders_response.get('files', [])
        unprocessed_id = None
        processed_id = None
        
        for folder in subfolders:
            folder_name = folder.get('name')
            if folder_name == 'Unprocessed':
                unprocessed_id = folder.get('id')
            elif folder_name == 'Processed':
                processed_id = folder.get('id')
                
        if not unprocessed_id or not processed_id:
            missing = []
            if not unprocessed_id:
                missing.append("'Unprocessed'")
            if not processed_id:
                missing.append("'Processed'")
            raise ValueError(
                f"Found job folder '{job_name}' inside 'ATS Master Folder', but it is missing the required subfolder(s): {', '.join(missing)}."
            )
            
        return {
            "unprocessed_id": unprocessed_id,
            "processed_id": processed_id
        }
        
    except HttpError as error:
        raise ValueError(f"Google Drive API error: {error.reason or str(error)}")

