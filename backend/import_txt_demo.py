from annotation2.services import project_service, import_service, document_service

def main():
    # Clean up existing 'Batch' project if it exists
    projects = project_service.list_projects()
    for old_p in projects:
        if old_p.name == "Batch":
            print(f"Deleting existing project: {old_p.name} (ID: {old_p.id})")
            project_service.delete_project(old_p.id)
            break

    p = project_service.create_project("Batch", ["PER","LOC","ORG"])

    import pathlib
    base = pathlib.Path(__file__).parent.parent
    files = [str(base / "sample1.txt"), str(base / "sample2.txt")]
    
    # Check if files exist to avoid errors
    files = [f for f in files if pathlib.Path(f).exists()]
    if not files:
        print("No sample files found.")
        return

    import_service.import_txt_files(p.id, files, strategy="sentence")
    docs = document_service.list_documents(p.id, limit=10, offset=0)
    print([d.id for d in docs])

if __name__ == "__main__":
    main()