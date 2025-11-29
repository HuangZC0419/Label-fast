from annotation2.services import project_service, import_service, document_service

def main():
    p = project_service.create_project("Batch", ["PER","LOC","ORG"])
    import_service.import_txt_files(p.id, ["sample1.txt", "sample2.txt"], strategy="sentence")
    docs = document_service.list_documents(p.id, limit=10, offset=0)
    print([d.id for d in docs])

if __name__ == "__main__":
    main()