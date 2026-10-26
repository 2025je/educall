package org.edumeeting.ui

import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActionScope
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material.icons.filled.Face
import androidx.compose.material.icons.filled.Lock
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.unit.dp

val FieldShape = RoundedCornerShape(12.dp)

/** Conserva solo dígitos y recorta a [maxLength]; se usa en PIN y códigos numéricos. */
fun digitsOnly(value: String, maxLength: Int): String = value.filter(Char::isDigit).take(maxLength)

/**
 * Campo de formulario de una línea con navegación por teclado.
 *
 * Con [ImeAction.Next] la tecla Enter pasa al siguiente campo (o llama a [onSubmit] si se indica).
 * Con cualquier otra acción (Done, Go, Search, Send) cierra el teclado y llama a [onSubmit].
 */
@Composable
fun FormTextField(
    value: String,
    onValueChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    leadingIcon: ImageVector? = null,
    placeholder: String? = null,
    supportingText: String? = null,
    enabled: Boolean = true,
    isError: Boolean = false,
    keyboardType: KeyboardType = KeyboardType.Text,
    capitalization: KeyboardCapitalization = KeyboardCapitalization.None,
    imeAction: ImeAction = ImeAction.Next,
    onSubmit: (() -> Unit)? = null,
    clearable: Boolean = false,
    clearDescription: String = "Borrar $label",
    visualTransformation: VisualTransformation = VisualTransformation.None,
    trailingIcon: (@Composable () -> Unit)? = null,
) {
    val focusManager = LocalFocusManager.current
    val submit: KeyboardActionScope.() -> Unit = {
        if (imeAction == ImeAction.Next && onSubmit == null) {
            focusManager.moveFocus(FocusDirection.Down)
        } else {
            if (imeAction != ImeAction.Next) focusManager.clearFocus()
            onSubmit?.invoke()
        }
    }
    val trailing: (@Composable () -> Unit)? = trailingIcon ?: if (clearable && value.isNotEmpty() && enabled) {
        { IconButton(onClick = { onValueChange("") }) { Icon(Icons.Default.Clear, contentDescription = clearDescription) } }
    } else {
        null
    }
    OutlinedTextField(
        value = value,
        onValueChange = onValueChange,
        label = { Text(label) },
        placeholder = placeholder?.let { { Text(it) } },
        leadingIcon = leadingIcon?.let { { Icon(it, contentDescription = null) } },
        trailingIcon = trailing,
        supportingText = supportingText?.let { { Text(it) } },
        enabled = enabled,
        isError = isError,
        singleLine = true,
        shape = FieldShape,
        visualTransformation = visualTransformation,
        keyboardOptions = KeyboardOptions(capitalization = capitalization, keyboardType = keyboardType, imeAction = imeAction),
        keyboardActions = KeyboardActions(
            onNext = submit, onDone = submit, onGo = submit, onSearch = submit, onSend = submit,
        ),
        modifier = modifier,
    )
}

/** Contraseña con botón para mostrarla u ocultarla. */
@Composable
fun PasswordField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String = "Contraseña",
    enabled: Boolean = true,
    imeAction: ImeAction = ImeAction.Done,
    onSubmit: (() -> Unit)? = null,
) {
    var visible by rememberSaveable { mutableStateOf(false) }
    FormTextField(
        value = value,
        onValueChange = onValueChange,
        label = label,
        modifier = modifier,
        leadingIcon = Icons.Default.Lock,
        enabled = enabled,
        keyboardType = KeyboardType.Password,
        imeAction = imeAction,
        onSubmit = onSubmit,
        visualTransformation = if (visible) VisualTransformation.None else PasswordVisualTransformation(),
        trailingIcon = {
            IconButton(onClick = { visible = !visible }) {
                Icon(
                    if (visible) Icons.Default.Lock else Icons.Default.Face,
                    contentDescription = if (visible) "Ocultar ${label.lowercase()}" else "Mostrar ${label.lowercase()}",
                )
            }
        },
    )
}

/** PIN numérico oculto; filtra lo que no sea dígito y limita la longitud. */
@Composable
fun PinField(
    value: String,
    onValueChange: (String) -> Unit,
    modifier: Modifier = Modifier,
    label: String = "PIN",
    supportingText: String? = null,
    maxLength: Int = 8,
    enabled: Boolean = true,
    isError: Boolean = false,
    imeAction: ImeAction = ImeAction.Done,
    onSubmit: (() -> Unit)? = null,
) {
    FormTextField(
        value = value,
        onValueChange = { onValueChange(digitsOnly(it, maxLength)) },
        label = label,
        modifier = modifier,
        leadingIcon = Icons.Default.Lock,
        supportingText = supportingText,
        enabled = enabled,
        isError = isError,
        keyboardType = KeyboardType.NumberPassword,
        imeAction = imeAction,
        onSubmit = onSubmit,
        visualTransformation = PasswordVisualTransformation(),
    )
}