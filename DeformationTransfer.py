#Code by Chris Tralie, Parit Burintrathikul, Justin Wang, Lydia Xu, Billy Wan, and Jay Wang
import sys
sys.path.append("S3DGLPy")
from Primitives3D import *
from PolyMesh import *
import numpy as np
from scipy import sparse
import scipy.io as sio
from scipy.linalg import norm
from scipy.sparse.linalg import lsqr

def loadBaselKeypointMesh():
    (VPos, VColors, ITris) = loadOffFileExternal("BUMesh.off")    
    return (VPos, ITris)
    
#Parit:load Meshidx and mesh of statue
def loadBUTris():
    ITris = sio.loadmat("BaselTris.mat")['ITris']
    return ITris

def getLaplacianMatrixCotangent(mesh, anchorsIdx, anchorWeights = 1):
    VPos = mesh.VPos
    ITris = mesh.ITris
    N = VPos.shape[0]
    M = ITris.shape[0]
    #Allocate space for the sparse array storage, with 2 entries for every
    #edge for every triangle (6 entries per triangle); one entry for directed 
    #edge ij and ji.  Note that this means that edges with two incident triangles
    #will have two entries per directed edge, but sparse array will sum them 
    I = np.zeros(M*6)
    J = np.zeros(M*6)
    V = np.zeros(M*6)
    
    #Keep track of areas of incident triangles and the number of incident triangles
    IA = np.zeros(M*3)
    VA = np.zeros(M*3) #Incident areas
    VC = 1.0*np.ones(M*3) #Number of incident triangles
    
    #Step 1: Compute cotangent weights
    for shift in range(3): 
        #For all 3 shifts of the roles of triangle vertices
        #to compute different cotangent weights
        [i, j, k] = [shift, (shift+1)%3, (shift+2)%3]
        dV1 = VPos[ITris[:, i], :] - VPos[ITris[:, k], :]
        dV2 = VPos[ITris[:, j], :] - VPos[ITris[:, k], :]
        Normal = np.cross(dV1, dV2)
        #Cotangent is dot product / mag cross product
        NMag = np.sqrt(np.sum(Normal**2, 1))
        cotAlpha = np.sum(dV1*dV2, 1)/NMag
        I[shift*M*2:shift*M*2+M] = ITris[:, i]
        J[shift*M*2:shift*M*2+M] = ITris[:, j] 
        V[shift*M*2:shift*M*2+M] = cotAlpha
        I[shift*M*2+M:shift*M*2+2*M] = ITris[:, j]
        J[shift*M*2+M:shift*M*2+2*M] = ITris[:, i] 
        V[shift*M*2+M:shift*M*2+2*M] = cotAlpha
        if shift == 0:
            #Compute contribution of this triangle to each of the vertices
            for k in range(3):
                IA[k*M:(k+1)*M] = ITris[:, k]
                VA[k*M:(k+1)*M] = 0.5*NMag
    
    #Step 2: Create laplacian matrix
    L = sparse.coo_matrix((V, (I, J)), shape=(N, N)).tocsr()
    #Create the diagonal by summing the rows and subtracting off the nondiagonal entries
    L = sparse.dia_matrix((L.sum(1).flatten(), 0), L.shape) - L
    
    #Step 3: Add anchors
    L = L.tocoo()
    I = L.row.tolist()
    J = L.col.tolist()
    V = L.data.tolist()
    I = I + range(N, N+len(anchorsIdx))
    J = J + anchorsIdx.tolist()
    V = V + [anchorWeights]*len(anchorsIdx)
    L = sparse.coo_matrix((V, (I, J)), shape=(N+len(anchorsIdx), N)).tocsr()
    return L

def solveLaplacianMesh(mesh, anchors, anchorsIdx):
    N = mesh.VPos.shape[0]
    L = getLaplacianMatrixCotangent(mesh, anchorsIdx)
    delta = L.dot(mesh.VPos)
    delta[N:, :] = anchors
    for k in range(3):
        mesh.VPos[:, k] = lsqr(L, delta[:, k])[0]
    mesh.saveFile("out.off")

class VideoMesh(object):
    def __init__(self):
        self.Frames = np.array([])
    
    def initStaticVideo(VPosInitial):
        self.Frames = np.array(VPosInitial)
        self.Frames = np.reshape(self.Frames, (1, self.Frames.shape[0], self.Frames.shape[1]))

class DeformationTranferer:
    def __init__(self, origVideo, warpedVideo):
        self.origVideo = origVideo
        self.warpedVideo = warpedVideo
        self.origFrames = self.origVideo.Frames
        self.warpedFrames = self.warpedVideo.Frames
        self.origMesh = self.origVideo.m
        self.warpedMesh = self.warpedVideo.m
        self.NFrames = self.origFrames.shape[0]
        self.NFaces = len(self.origMesh.faces)
        assert self.origFrames.shape[1] == len(self.origMesh.vertices) \
               and len(self.origMesh.vertices) == len(self.warpedMesh.vertices) \
               and len(self.warpedMesh.vertices) == self.warpedFrames.shape[1] \
               and len(self.origMesh.faces) == len(self.warpedMesh.faces)

        self.count = 0
        self.NVertices = self.origFrames.shape[1]
        self.NVertices4 = self.NVertices + self.NFaces #original vertices plus 1 new vertex (4th vector) for each face
        self.origMesh.updateTris()
        self.warpedMesh.updateTris()
        self.origTris = self.origMesh.ITris
        self.warpedTris = self.warpedMesh.ITris
        assert self.origTris.shape[0] == self.warpedTris.shape[0]
        # Tris4 is Tris plus 4th col indexing 4th vector (which should be mapped to the N to N+F-1 index of VPos4)
        self.origTris4 = np.hstack((self.origTris,
                                    np.reshape(np.arange(self.NVertices, self.NVertices4), (self.NFaces, 1))))
        self.warpedTris4 = np.hstack((self.warpedTris,
                                    np.reshape(np.arange(self.NVertices, self.NVertices4), (self.NFaces, 1))))
        print "#####debug info: initial values#########"
        print "origFrame shape (NFrames x NVertices x 3):", self.origFrames.shape
        print "warpedFrame shape (NFrames x NVertices x 3): ", self.warpedFrames.shape
        print "origMesh number of vertices:", len(self.origMesh.vertices)
        print "warpedMesh number of vertices:", len(self.warpedMesh.vertices)
        print "origMesh number of faces:", len(self.origMesh.faces)
        print "warpedMesh number of faces:", len(self.warpedMesh.faces)
        print "origMesh ITris shape:", self.origMesh.ITris.shape
        print "warpedMesh ITris shape:", self.warpedMesh.ITris.shape
        print "#####end: initial values#########"

    def beginDeformationTransfer(self):
        resultFrames = np.empty([self.NFrames, self.NVertices, 3])  # this is result array to fill in
        resultFrames[0, :, :] = self.warpedFrames[0, :, :]
        origOldVPos4 = self.getVPos4(self.origFrames[0, :, :], self.origTris)  # old VPos with extra NFaces vectors
        warpedOldVPos4 = self.getVPos4(self.warpedFrames[0, :, :], self.warpedTris)
        for i in range(1, self.NFrames):
            # 1 orig: get newVPos4
            origNewVPos4 = self.getVPos4(self.origFrames[i, :, :], self.origTris)
            # 2 orig: use old and new VPos4 to get S-matrix which shape is 3 x 3NFaces
            S = self.getSMatrix(origOldVPos4, origNewVPos4, self.origTris4)
            # 3 warped: use old VPos4 to get A (coefficient) sparse matrix which shape is 3NFaces x NVertices
            A = self.getAMatrix(warpedOldVPos4, self.warpedTris4)
            origOldVPos4 = origNewVPos4
            warpedOldVPos4[:, 0] = lsqr(A, S[0, :])[0]
            warpedOldVPos4[:, 1] = lsqr(A, S[1, :])[0]
            warpedOldVPos4[:, 2] = lsqr(A, S[2, :])[0]
           # print "new VPos4 shape:", warpedOldVPos4[np.arange(self.NVertices), :].shape
            resultFrames[i, :, :] = warpedOldVPos4[np.arange(self.NVertices), :]
        self.warpedVideo.Frames = resultFrames



    #get VPos4 (each face has 4 vertices) from VPos3 (each face 3 vertices) with mesh topology given
    def getVPos4(self, VPos3, ITris3):
        V4 = self.get4thVertex(VPos3, ITris3)
        VPos4 = np.vstack((VPos3, V4))
        return VPos4

    # get4thVertex for each face, aka face normal scaled by reciprocal of sqrt of its length
    # (3 vertices's index are stored in every row in ITris)
    def get4thVertex(self, VPos3, ITris3):
        V1 = VPos3[ITris3[:, 1], :] - VPos3[ITris3[:, 0], :]
        V2 = VPos3[ITris3[:, 2], :] - VPos3[ITris3[:, 0], :]
        FNormals = np.cross(V1, V2)

        FNormalsSqrtLength = np.sqrt(np.sum(FNormals**2, 1))[:, None]
        F = FNormals/FNormalsSqrtLength
        Vertex4 = VPos3[ITris3[:, 0], :] + F
        return Vertex4

    def getSMatrix(self, oldVPos4, newVPos4, Tris4):
        v2subv1 = oldVPos4[Tris4[:, 1], :] - oldVPos4[Tris4[:, 0], :]
        v3subv1 = oldVPos4[Tris4[:, 2], :] - oldVPos4[Tris4[:, 0], :]
        v4subv1 = oldVPos4[Tris4[:, 3], :] - oldVPos4[Tris4[:, 0], :]
        tildev2subv1 = newVPos4[Tris4[:, 1], :] - newVPos4[Tris4[:, 0], :]
        tildev3subv1 = newVPos4[Tris4[:, 2], :] - newVPos4[Tris4[:, 0], :]
        tildev4subv1 = newVPos4[Tris4[:, 3], :] - newVPos4[Tris4[:, 0], :]
        assert self.NFaces == Tris4.shape[0]
        S = np.zeros((3, 0))
        for i in range(0, self.NFaces):
            vInv = np.linalg.inv((np.vstack((v2subv1[i, :], v3subv1[i, :], v4subv1[i, :]))).T)
            tildev = (np.vstack((tildev2subv1[i, :], tildev3subv1[i, :], tildev4subv1[i, :]))).T
            S = np.hstack((S, np.dot(tildev, vInv)))
        return S

    def getAMatrix(self, VPos4, Tris4):
        # I, J, and V are parallel numpy arrays that hold the rows, columns, and values of nonzero elements
        I = []
        J = []
        V = []
        v2subv1 = VPos4[Tris4[:, 1], :] - VPos4[Tris4[:, 0], :]
        v3subv1 = VPos4[Tris4[:, 2], :] - VPos4[Tris4[:, 0], :]
        v4subv1 = VPos4[Tris4[:, 3], :] - VPos4[Tris4[:, 0], :]
        assert self.NFaces == Tris4.shape[0]

        for i in range(0, self.NFaces):
            idxRow = i * 3
            vInv = np.linalg.inv((np.vstack((v2subv1[i, :], v3subv1[i, :], v4subv1[i, :]))).T)  # 3x3
            sumOfNegativevInv = np.sum(-1 * vInv, axis = 0) # shape is (3,)
            ###################   ######
            # -A-D-G, A, D, G #   # x1 #
            # -B-E-H, B, E, H # X # x2 #
            # -C-F-I, C, F, I #   # x3 #
            ###################   # x4 #
                                  ######

            # sumOfNegativevInv current looks like this, take care when fill in I, J, V
            ##########################
            # -A-D-G, -B-E-H, -C-F-I #
            ##########################
            for j in range(0, 3):
                I.append(idxRow + j)
                J.append(Tris4[i, 0])
                V.append(sumOfNegativevInv[j])
            # vInv current looks like this. Same, be careful.
            ###########
            # A, B, C #
            # D, E, F #
            # G, H, I #
            ###########
            for j in range(0, 3):
                for k in range(0, 3):
                    I.append(idxRow + k)
                    J.append(Tris4[i, j + 1])
                    V.append(vInv[j, k])
        A = sparse.coo_matrix((V, (I, J)), shape = (3 * self.NFaces, self.NVertices4)).tocsr()
        return A

class VideoMesh(object):
    def __init__(self, initialMeshFilename):
        self.m = PolyMesh()
        self.m.loadFile(initialMeshFilename)
        if( (initialMeshFilename == 'NotreDameFrontHalfMouthCut.off')):
            self.m.VPos[:,2] = -self.m.VPos[:,2]
            self.m.needsDisplayUpdate = True

        #Frames is an NFrames x NVertices x 3 array of vertices for the
        #mesh video
        #By default, just make a video with one frame as the initial mesh
        #position
        #Jay: here it's taking the VPos (a list of position of every vertex) and make it the 1-frame frame
        self.Frames = np.array(self.m.VPos)
        self.Frames = np.reshape(self.Frames, (1, self.Frames.shape[0], self.Frames.shape[1]))
        self.bbox = BBox3D()
        self.bbox.fromPoints(self.m.VPos)
    
    def loadVideo(self, videoFilename):
        self.Frames = sio.loadmat(videoFilename)['Frames']

    def doTransfer(self):
        return

    def drawFrame(self, idx, displayMeshEdges, displayMeshPoints, displayMeshFaces):
        if idx >= self.Frames.shape[0]:
            #If beyond the end of the video, just play the last frame
            idx = self.Frames.shape[0]-1
        self.m.VPos = self.Frames[idx, :, :]
        self.m.needsDisplayUpdate = True
        self.m.renderGL(displayMeshEdges, displayMeshPoints, displayMeshFaces, False, False, True, False)

if __name__ == '__main__':
    #Load the original video of Chris talking with the candide mesh
    #over his face geometry
    self.origVideo = VideoMesh('candide.off')
    self.origVideo.loadVideo('SpeechVideo1.mat')
    #Load the first candide frame
    self.warpedVideo = VideoMesh('StatueCandide.off')
    #TODO: You can have a look at the data structures here