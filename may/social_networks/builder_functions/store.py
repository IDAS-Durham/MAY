"""
Shared storage function for all network builder functions.

All builders must use store_contacts to write to person.properties and
person.activity_map. See network_builder_function_requirements.md.
"""


def store_contacts(person, contacts, storage_key: str,
                   activity_config: dict | None = None) -> None:
    """
    Write contacts into person.properties[storage_key], accumulating across calls.

    contacts: iterable of Person objects to store
    activity_config: optional dict with 'contact_activity_key' and 'activity_key'.
        If provided, merges contact.activity_map[contact_activity_key] into
        person.activity_map[activity_key] for each contact.
    """
    new_contacts = set(contacts)
    if storage_key in person.properties:
        person.properties[storage_key].update(new_contacts)
    else:
        person.properties[storage_key] = new_contacts

    if activity_config and new_contacts:
        contact_activity_key = activity_config["contact_activity_key"]
        activity_key = activity_config["activity_key"]
        person.activities.add(activity_key)
        for contact in new_contacts:
            if contact_activity_key in contact.activity_map:
                if activity_key not in person.activity_map:
                    person.activity_map[activity_key] = {}
                target = person.activity_map[activity_key]
                for venue_type, subsets in contact.activity_map[contact_activity_key].items():
                    if venue_type not in target:
                        target[venue_type] = list(subsets)
                    else:
                        target[venue_type].extend(subsets)
