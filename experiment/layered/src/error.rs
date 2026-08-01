//! One error type per layer, converted upwards on the way out.

use conformance::{Error as ApiError, ListId, TodoId};

/// Failures the storage layer can produce.
#[derive(Debug)]
pub enum RepoError {
    Sql(rusqlite::Error),
    ListNotFound(ListId),
    TodoNotFound(TodoId),
}

impl From<rusqlite::Error> for RepoError {
    fn from(err: rusqlite::Error) -> Self {
        RepoError::Sql(err)
    }
}

/// Failures the business layer can produce, including anything from below it.
#[derive(Debug)]
pub enum ServiceError {
    Repo(RepoError),
    InvalidTitle,
    OpenChildren { todo: TodoId, open: usize },
    WouldCycle { todo: TodoId, parent: TodoId },
}

impl From<RepoError> for ServiceError {
    fn from(err: RepoError) -> Self {
        ServiceError::Repo(err)
    }
}

impl From<rusqlite::Error> for ServiceError {
    fn from(err: rusqlite::Error) -> Self {
        ServiceError::Repo(RepoError::Sql(err))
    }
}

impl From<ServiceError> for ApiError {
    fn from(err: ServiceError) -> Self {
        match err {
            ServiceError::Repo(RepoError::Sql(sql)) => ApiError::Storage(sql.to_string()),
            ServiceError::Repo(RepoError::ListNotFound(id)) => ApiError::NoSuchList(id),
            ServiceError::Repo(RepoError::TodoNotFound(id)) => ApiError::NoSuchTodo(id),
            ServiceError::InvalidTitle => ApiError::EmptyTitle,
            ServiceError::OpenChildren { todo, open } => ApiError::OpenChildren { todo, open },
            ServiceError::WouldCycle { todo, parent } => ApiError::WouldCycle { todo, parent },
        }
    }
}

pub type RepoResult<T> = std::result::Result<T, RepoError>;
pub type ServiceResult<T> = std::result::Result<T, ServiceError>;
