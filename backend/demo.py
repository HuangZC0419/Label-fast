from annotation2.services import project_service, document_service, annotation_service, relation_service, export_service

def main():
    # Clean up existing 'Demo' project if it exists
    projects = project_service.list_projects()
    for old_p in projects:
        if old_p.name == "Demo":
            print(f"Deleting existing project: {old_p.name} (ID: {old_p.id})")
            project_service.delete_project(old_p.id)
            break

    print("Creating new project: Demo")
    p = project_service.create_project("Demo", ["PER","LOC","ORG"])
    p = project_service.update_relation_types(p.id, ["LOCATED_IN","WORKS_AT","FOUNDED_IN"]) 
    docs = document_service.import_texts(p.id, ["Mike lives in America.", "Apple is a company.", "Beijing is in China."])
    a1 = annotation_service.add_span(docs[0].id, 0, 4, "PER")
    a2 = annotation_service.add_span(docs[0].id, 15, 22, "LOC")
    r1 = relation_service.add_relation(docs[0].id, a1.id, a2.id, "LOCATED_IN")
    path_jsonl = export_service.export_project(p.id, "jsonl")
    path_tsv = export_service.export_project(p.id, "tsv")
    print({"project": p, "docs": [d.id for d in docs], "annotations": [a1.id, a2.id], "relation": r1.id, "jsonl": path_jsonl, "tsv": path_tsv})

if __name__ == "__main__":
    main()