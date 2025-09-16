"""Conversation state constants."""

# Estados conversación /add
ADD_NOMBRE, ADD_APELLIDO, ADD_TELEFONO, ADD_DNI, ADD_ESTADO, ADD_CANCEL_CONFIRM = range(6)

# Estados conversación administración (Usuarios permitidos)
ADM_ADD_ID, ADM_DEL_ID = range(6, 8)

# Estados conversación administración (Admins)
ADM_ADM_ADD_ID, ADM_ADM_DEL_ID = range(8, 10)

# Estado para observación "Contactar Luego"
EDIT_OBS = 100

