from annotation2.services import project_service, document_service, annotation_service, export_service

def main():
    p = project_service.create_project("Demo", ["PER","LOC","ORG"])
    docs = document_service.import_texts(p.id, ["Mike lives in America.", "Apple is a company.", "Beijing is in China."])
    a1 = annotation_service.add_span(docs[0].id, 0, 4, "PER")
    a2 = annotation_service.add_span(docs[0].id, 15, 22, "LOC")
    path_jsonl = export_service.export_project(p.id, "jsonl")
    path_tsv = export_service.export_project(p.id, "tsv")
    print({"project": p, "docs": [d.id for d in docs], "annotations": [a1.id, a2.id], "jsonl": path_jsonl, "tsv": path_tsv})

if __name__ == "__main__":
    main()